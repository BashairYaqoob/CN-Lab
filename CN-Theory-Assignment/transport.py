#!/usr/bin/env python3
"""
transport.py - Go-Back-N (GBN) and Selective Repeat (SR) over a simulated
unreliable satellite link.
Model (all times in milliseconds of *simulated* time)
-----------------------------------------------------
* Link: R = 2 Mbps, RTT = 500 ms (one-way propagation 250 ms), L = 1000 bytes.
  Serialisation time of one data packet = L/R = 4 ms.  Data packets leave the
  sender one at a time (the link is busy for 4 ms per packet).  ACKs are tiny,
  so their serialisation time is ignored (assumption).
* Channel: every packet AND every ACK can be lost, corrupted or delayed, with
  independent probabilities.  Corruption flips one random bit; the receiver /
  sender detects it with a 16-bit Internet checksum and treats the packet as
  if it had never arrived (rdt 3.0 behaviour).
* Delay: with probability --delay a packet gets an extra delay drawn uniformly
  from [--delay-min, --delay-max] ms (default 20-100 ms; this can re-order packets).
* Order: by default the channel is FIFO - a delayed packet also holds up the packets
  behind it (rdt 3.0 / GBN textbook assumption).  --reorder lets later packets
  overtake delayed ones (SR is designed for that; GBN windows may then be unsafe).
* Timeout: default 800 ms.  Worst-case RTT = 500 + 12 (4 packets x 4 ms) + 2 x 100
  = 712 ms < 800 ms, so a timeout never fires prematurely and no old copy of a
  packet is still in the network when a retransmission is sent.  This is the
  "maximum packet lifetime" assumption that k-bit sequence numbers always need.
* Sequence numbers on the wire are k bits (wrap modulo 2^k).  Inside the
  sender, base / nextseqnum are kept as ABSOLUTE counters (0,1,2,...) so the
  logs are easy to read; the number that travels in the packet is
  (counter mod 2^k).  The log prints both, e.g.  base=9(s1).
* Slide terminology (Chapter 3): base, nextseqnum, expectedseqnum, rcv_base,
  cumulative ACK, sender window, receiver window.

Usage example
-------------
  python transport.py --protocol sr --packets 200 --window 4 --seq-bits 3 \
         --loss 0.05 --corrupt 0.05 --delay 0.10 --timeout 800 --seed 810 --quiet
"""
import argparse
import copy
import heapq
import random
import sys
import time
from collections import Counter
from dataclasses import dataclass, field

# --------------------------------------------------------------------------
# Scenario constants
# --------------------------------------------------------------------------
LINK_RATE_BPS = 2_000_000      # R = 2 Mbps
RTT_MS = 500.0                 # RTT = 500 ms
PKT_BYTES = 1000               # L = 1000 bytes = 8000 bits


@dataclass
class Config:
    protocol: str = "gbn"          # "gbn" or "sr"
    packets: int = 200             # number of data packets to transfer
    window: int = 4                # N
    seq_bits: int = 3              # k  -> sequence numbers 0 .. 2^k - 1
    loss: float = 0.0              # P(loss)       (data and ACK)
    corrupt: float = 0.0           # P(corruption) (data and ACK)
    delay: float = 0.0             # P(extra delay)(data and ACK)
    delay_min_ms: float = 20.0     # extra delay range when a packet is delayed
    delay_max_ms: float = 100.0
    timeout_ms: float = 800.0      # retransmission timeout, > worst-case RTT (see header)
    reorder: bool = False          # False: delayed packets hold up later ones (FIFO channel)
    seed: int = 810                # last four digits of roll number 0810
    drop_first: tuple = ()         # scripted: drop 1st transmission of these packet indices
    max_time_ms: float = 3_600_000.0   # safety stop (1 hour of simulated time)
    link_rate_bps: float = LINK_RATE_BPS
    rtt_ms: float = RTT_MS
    pkt_bytes: int = PKT_BYTES

    @property
    def modulus(self):             # number of sequence numbers = 2^k
        return 2 ** self.seq_bits

    @property
    def tx_ms(self):               # L / R in ms
        return self.pkt_bytes * 8 / self.link_rate_bps * 1000.0

    @property
    def prop_ms(self):             # one-way propagation delay
        return self.rtt_ms / 2.0

    def validate(self):
        if self.protocol not in ("gbn", "sr"):
            raise ValueError("protocol must be gbn or sr")
        for name in ("loss", "corrupt", "delay"):
            if not 0.0 <= getattr(self, name) <= 1.0:
                raise ValueError(f"--{name} must be between 0 and 1")
        if self.window < 1 or self.packets < 1 or self.seq_bits < 1:
            raise ValueError("window, packets and seq-bits must be >= 1")
        if self.window > self.modulus - 1:
            raise ValueError(f"window {self.window} too large for {self.seq_bits}-bit "
                             f"sequence numbers (max {self.modulus - 1} even for GBN)")


# --------------------------------------------------------------------------
# Packets and checksum
# --------------------------------------------------------------------------
def checksum16(data: bytes) -> int:
    """16-bit Internet checksum (one's-complement sum of 16-bit words)."""
    if len(data) % 2:
        data += b"\x00"
    total = 0
    for i in range(0, len(data), 2):
        total += (data[i] << 8) | data[i + 1]
        total = (total & 0xFFFF) + (total >> 16)      # end-around carry
    return (~total) & 0xFFFF


class Packet:
    """DATA or ACK segment.  `idx` is simulator bookkeeping (absolute packet
    number) used only for logging - it is NOT part of the protocol header."""

    def __init__(self, kind, seq, payload=b"", idx=None):
        self.kind, self.seq, self.payload, self.idx = kind, seq, payload, idx
        self.chk = checksum16(self._body())

    def _body(self):
        return bytes([1 if self.kind == "DATA" else 2]) + self.seq.to_bytes(2, "big") + self.payload

    def is_corrupt(self):
        return checksum16(self._body()) != self.chk

    def corrupted_copy(self, rng):
        """Copy of this packet with exactly one bit flipped (checksum left stale)."""
        p = copy.copy(self)
        if self.payload:
            pos = rng.randrange(len(self.payload) * 8)
            b = bytearray(self.payload)
            b[pos // 8] ^= 1 << (pos % 8)
            p.payload = bytes(b)
        else:                                       # ACK: flip a bit of the seq field
            p.seq = self.seq ^ (1 << rng.randrange(16))
        return p

    def name(self):
        tag = f"#{self.idx}" if self.idx is not None else ""
        return f"{self.kind} seq={self.seq}{(' ' + tag) if tag else ''}"


def make_payload(i, size=PKT_BYTES):
    """Deterministic application data for packet i (lets us verify the result)."""
    return random.Random(10_000 + i).randbytes(size)


# --------------------------------------------------------------------------
# Simulation context: clock, event queue, unreliable channel, log
# --------------------------------------------------------------------------
class Net:
    def __init__(self, cfg: Config, echo=True):
        self.cfg, self.echo = cfg, echo
        self.t = 0.0
        self._q, self._n = [], 0
        self.rng = random.Random(cfg.seed)
        self.link_free = 0.0                 # time the sender's link becomes idle
        self.lines, self.events = [], []
        self.stats = Counter()
        self._first_seen = set()
        self._last_arrival = {"R": 0.0, "S": 0.0}   # for the FIFO option

    # ---- event queue -----------------------------------------------------
    def schedule(self, when, kind, *args):
        heapq.heappush(self._q, (when, self._n, kind, args))
        self._n += 1

    # ---- logging ---------------------------------------------------------
    def emit(self, who, ev, msg, **fields):
        line = f"[{self.t:10.1f} ms] {who:<8} {ev:<9} {msg}"
        self.lines.append(line)
        if self.echo:
            print(line)
        evt = dict(t=self.t, who=who, ev=ev, msg=msg, **fields)
        self.events.append(evt)
        return evt

    # ---- the unreliable channel -----------------------------------------
    def transmit(self, pkt: Packet, to: str):
        """to = 'R' (sender -> receiver, data) or 'S' (receiver -> sender, ACK)."""
        cfg = self.cfg
        # always draw the same three numbers so runs are reproducible
        r_loss, r_corr, r_delay = self.rng.random(), self.rng.random(), self.rng.random()

        if to == "R":                         # serialise data packets on the link
            start = max(self.t, self.link_free)
            self.link_free = start + cfg.tx_ms
            depart = self.link_free
        else:
            depart = self.t

        scripted = (pkt.kind == "DATA" and pkt.idx in cfg.drop_first
                    and pkt.idx not in self._first_seen)
        if pkt.kind == "DATA":
            self._first_seen.add(pkt.idx)

        if scripted or r_loss < cfg.loss:                           # ---- LOSS
            self.stats["data_lost" if pkt.kind == "DATA" else "ack_lost"] += 1
            self.emit("CHANNEL", "LOSS", f"{pkt.name()} lost" + (" (scripted)" if scripted else ""),
                      kind=pkt.kind, idx=pkt.idx, seq=pkt.seq)
            return

        if r_corr < cfg.corrupt:                                    # ---- CORRUPTION
            pkt = pkt.corrupted_copy(self.rng)
            self.stats["data_corrupted" if pkt.kind == "DATA" else "ack_corrupted"] += 1
            self.emit("CHANNEL", "CORRUPT", f"{pkt.name()} corrupted (bit flipped)",
                      kind=pkt.kind, idx=pkt.idx, seq=pkt.seq)
        else:
            pkt = copy.copy(pkt)

        arrive = depart + cfg.prop_ms
        if r_delay < cfg.delay:                                     # ---- DELAY
            extra = self.rng.uniform(cfg.delay_min_ms, cfg.delay_max_ms)
            arrive += extra
            self.stats["delayed"] += 1
            self.emit("CHANNEL", "DELAY", f"{pkt.name()} delayed +{extra:.0f} ms",
                      kind=pkt.kind, idx=pkt.idx, seq=pkt.seq)
        if not cfg.reorder:                                         # FIFO: no overtaking
            arrive = max(arrive, self._last_arrival[to])
            self._last_arrival[to] = arrive
        self.schedule(arrive, "to_" + to, pkt)


# --------------------------------------------------------------------------
# Go-Back-N
# --------------------------------------------------------------------------
class GBNSender:
    """base = oldest unACKed packet, nextseqnum = next packet to send.
    ONE timer (for the oldest unACKed packet).  ACKs are cumulative.
    On timeout: resend every packet in [base, nextseqnum-1]."""

    def __init__(self, net, data):
        self.net, self.cfg, self.data = net, net.cfg, data
        self.M, self.N, self.n = net.cfg.modulus, net.cfg.window, len(data)
        self.base = 0
        self.nextseqnum = 0
        self.sndpkt = {}                  # idx -> Packet (kept until ACKed)
        self.timer_token, self.timer_on = 0, False
        self.done = False

    def _state(self):
        M = self.M
        return (f"base={self.base}(s{self.base % M}) nextseqnum={self.nextseqnum}(s{self.nextseqnum % M})"
                f" window=[{self.base}-{self.base + self.N - 1}]")

    def _win(self):
        if self.base >= self.n:
            return "all ACKed"
        return f"[{self.base}-{min(self.base + self.N - 1, self.n - 1)}]"

    def start_timer(self):
        self.timer_token += 1
        self.timer_on = True
        self.net.schedule(self.net.t + self.cfg.timeout_ms, "timer", self.timer_token)

    def stop_timer(self):
        self.timer_on = False
        self.timer_token += 1

    def _send(self, idx, retx):
        pkt = self.sndpkt[idx]
        self.net.stats["data_tx"] += 1
        if retx:
            self.net.stats["retx"] += 1
        self.net.emit("SENDER", "RETX" if retx else "SEND", f"{pkt.name()}  {self._state()}",
                      idx=idx, retx=retx, win=self._win())
        self.net.transmit(pkt, "R")

    def pump(self):
        """rdt_send(): send new packets while the window is not full."""
        while self.nextseqnum < self.n and self.nextseqnum < self.base + self.N:
            idx = self.nextseqnum
            self.sndpkt[idx] = Packet("DATA", idx % self.M, self.data[idx], idx)
            self._send(idx, retx=False)
            if self.base == self.nextseqnum:          # first outstanding packet -> start timer
                self.start_timer()
            self.nextseqnum += 1

    def on_ack(self, pkt):
        if pkt.is_corrupt():
            self.net.emit("SENDER", "IGNORE", f"ACK corrupted (checksum fails) - ignored",
                          win=self._win())
            return
        for idx in range(self.base, self.nextseqnum):     # cumulative: ACK n covers everything <= n
            if idx % self.M == pkt.seq:
                evt = self.net.emit("SENDER", "ACK-RECV",
                                    f"cumulative ACK {pkt.seq} -> packets up to #{idx} delivered", ack=pkt.seq,
                                    dup=False)
                self.base = idx + 1
                if self.base == self.nextseqnum:
                    self.stop_timer()
                else:
                    self.start_timer()                    # restart for the new oldest packet
                evt["win"] = self._win()
                if self.base >= self.n:
                    self.done = True
                    return
                self.pump()
                return
        self.net.emit("SENDER", "ACK-RECV", f"duplicate/old ACK {pkt.seq} - ignored  {self._state()}",
                      ack=pkt.seq, dup=True, win=self._win())

    def on_timeout(self, token):
        if token != self.timer_token or not self.timer_on:
            return                                        # stale timer event
        self.net.stats["timeouts"] += 1
        self.net.emit("SENDER", "TIMEOUT",
                      f"timer expired for oldest unACKed #{self.base} -> go back, resend "
                      f"#{self.base}..#{self.nextseqnum - 1}", win=self._win())
        self.start_timer()
        for idx in range(self.base, self.nextseqnum):
            self._send(idx, retx=True)


class GBNReceiver:
    """expectedseqnum = next in-order seq number.  Out-of-order / corrupt packets
    are discarded and the ACK of the last in-order packet is re-sent."""

    def __init__(self, net):
        self.net, self.M = net, net.cfg.modulus
        self.expectedseqnum = 0
        self.delivered = []
        self.last_ack = None

    def _send_ack(self, seq):
        self.net.stats["acks_sent"] += 1
        self.net.emit("RECEIVER", "ACK-SEND", f"ACK {seq} (cumulative)", ack=seq)
        self.net.transmit(Packet("ACK", seq), "S")

    def on_packet(self, pkt):
        win = f"expectedseqnum={self.expectedseqnum}"
        if pkt.is_corrupt():
            self.net.emit("RECEIVER", "DISCARD", f"{pkt.name()} corrupted - discard   {win}",
                          action="corrupt", idx=pkt.idx, seq=pkt.seq, rwin=win)
            self._reack(win)
        elif pkt.seq == self.expectedseqnum:
            self.delivered.append(pkt.payload)
            evt = self.net.emit("RECEIVER", "DELIVER", f"{pkt.name()} in order -> deliver to app   {win}",
                                action="deliver", idx=pkt.idx, seq=pkt.seq, rwin=win)
            self.last_ack = self.expectedseqnum
            self.expectedseqnum = (self.expectedseqnum + 1) % self.M
            evt["rwin"] = f"expectedseqnum={self.expectedseqnum}"        # state AFTER the packet
            self._send_ack(self.last_ack)
        else:
            self.net.emit("RECEIVER", "DISCARD",
                          f"{pkt.name()} out of order (expected {self.expectedseqnum}) - discard",
                          action="discard", idx=pkt.idx, seq=pkt.seq, rwin=win)
            self._reack(win)

    def _reack(self, win):
        if self.last_ack is None:
            self.net.emit("RECEIVER", "NO-ACK", "nothing delivered yet - no ACK to repeat", action_ack=None)
        else:
            self._send_ack(self.last_ack)


# --------------------------------------------------------------------------
# Selective Repeat
# --------------------------------------------------------------------------
class SRSender:
    """Sender window [base, base+N-1]; a timer per packet; individual ACKs;
    only the packet whose timer expires is resent."""

    def __init__(self, net, data):
        self.net, self.cfg, self.data = net, net.cfg, data
        self.M, self.N, self.n = net.cfg.modulus, net.cfg.window, len(data)
        self.base = 0
        self.nextseqnum = 0
        self.sndpkt, self.acked = {}, {}
        self.tok = {}                      # idx -> current timer token (per-packet timer)
        self.done = False

    def _state(self):
        M = self.M
        return (f"base={self.base}(s{self.base % M}) nextseqnum={self.nextseqnum}(s{self.nextseqnum % M})"
                f" window=[{self.base}-{self.base + self.N - 1}]")

    def _win(self):
        if self.base >= self.n:
            return "all ACKed"
        return f"[{self.base}-{min(self.base + self.N - 1, self.n - 1)}]"

    def start_timer(self, idx):
        self.tok[idx] = self.tok.get(idx, 0) + 1
        self.net.schedule(self.net.t + self.cfg.timeout_ms, "timer", idx, self.tok[idx])

    def cancel_timer(self, idx):
        self.tok[idx] = self.tok.get(idx, 0) + 1

    def _send(self, idx, retx):
        pkt = self.sndpkt[idx]
        self.net.stats["data_tx"] += 1
        if retx:
            self.net.stats["retx"] += 1
        self.net.emit("SENDER", "RETX" if retx else "SEND", f"{pkt.name()}  {self._state()}",
                      idx=idx, retx=retx, win=self._win())
        self.net.transmit(pkt, "R")
        self.start_timer(idx)

    def pump(self):
        while self.nextseqnum < self.n and self.nextseqnum < self.base + self.N:
            idx = self.nextseqnum
            self.sndpkt[idx] = Packet("DATA", idx % self.M, self.data[idx], idx)
            self.acked[idx] = False
            self._send(idx, retx=False)
            self.nextseqnum += 1

    def on_ack(self, pkt):
        if pkt.is_corrupt():
            self.net.emit("SENDER", "IGNORE", "ACK corrupted (checksum fails) - ignored", win=self._win())
            return
        for idx in range(self.base, self.nextseqnum):
            if idx % self.M == pkt.seq:
                if self.acked[idx]:
                    self.net.emit("SENDER", "ACK-RECV", f"duplicate ACK {pkt.seq} (#{idx} already ACKed) - ignored",
                                  ack=pkt.seq, dup=True, win=self._win())
                    return
                self.acked[idx] = True
                self.cancel_timer(idx)
                evt = self.net.emit("SENDER", "ACK-RECV", f"individual ACK {pkt.seq} -> #{idx} marked ACKed",
                                    ack=pkt.seq, dup=False)
                while self.base < self.nextseqnum and self.acked[self.base]:
                    self.base += 1                        # slide window past ACKed packets
                evt["win"] = self._win()
                if self.base >= self.n:
                    self.done = True
                    return
                self.pump()
                return
        self.net.emit("SENDER", "ACK-RECV", f"ACK {pkt.seq} outside window - ignored  {self._state()}",
                      ack=pkt.seq, dup=True, win=self._win())

    def on_timeout(self, idx, token):
        if self.tok.get(idx) != token or self.acked.get(idx, True):
            return                                        # stale timer / already ACKed
        self.net.stats["timeouts"] += 1
        self.net.emit("SENDER", "TIMEOUT", f"timer of #{idx} expired -> resend ONLY #{idx}", win=self._win())
        self._send(idx, retx=True)


class SRReceiver:
    """Receiver window [rcv_base, rcv_base+N-1].  Every correct packet inside the
    window is ACKed individually and buffered; delivery to the application is in
    order and slides rcv_base forward.  Packets from the previous window are
    re-ACKed (their ACK was probably lost)."""

    def __init__(self, net):
        self.net, self.M, self.N = net, net.cfg.modulus, net.cfg.window
        self.rcv_base = 0
        self.buffer = {}
        self.delivered = []

    def _rwin(self):
        return f"rcv_base={self.rcv_base} window=[{self.rcv_base}-{self.rcv_base + self.N - 1}]"

    def _send_ack(self, seq, note=""):
        self.net.stats["acks_sent"] += 1
        self.net.emit("RECEIVER", "ACK-SEND", f"ACK {seq} (individual){note}", ack=seq)
        self.net.transmit(Packet("ACK", seq), "S")

    def on_packet(self, pkt):
        M, N = self.M, self.N
        if pkt.is_corrupt():
            self.net.emit("RECEIVER", "DISCARD", f"{pkt.name()} corrupted - discard, no ACK   {self._rwin()}",
                          action="corrupt", idx=pkt.idx, seq=pkt.seq, rwin=self._rwin())
            return
        s = pkt.seq
        if (s - self.rcv_base) % M < N:                   # inside [rcv_base, rcv_base+N-1]
            fresh = s not in self.buffer
            if fresh:
                self.buffer[s] = pkt.payload
            in_order = (s == self.rcv_base)
            action = ("deliver" if in_order else "buffer") if fresh else "dup"
            text = ("in order" if in_order else "out of order -> BUFFERED") if fresh else "duplicate (already buffered)"
            evt = self.net.emit("RECEIVER", "BUFFER" if not in_order else "RECV",
                                f"{pkt.name()} {text}   {self._rwin()}",
                                action=action, idx=pkt.idx, seq=pkt.seq, rwin=self._rwin())
            self._send_ack(s)
            while self.rcv_base in self.buffer:           # deliver in order, slide window
                self.delivered.append(self.buffer.pop(self.rcv_base))
                self.net.emit("RECEIVER", "DELIVER",
                              f"seq {self.rcv_base} delivered to app in order (#{len(self.delivered) - 1})",
                              action="app", seq=self.rcv_base)
                self.rcv_base = (self.rcv_base + 1) % M
            evt["rwin"] = self._rwin()                           # state AFTER sliding
        elif 1 <= (self.rcv_base - s) % M <= N:           # inside [rcv_base-N, rcv_base-1]
            self.net.emit("RECEIVER", "RECV", f"{pkt.name()} already delivered - re-ACK   {self._rwin()}",
                          action="reack", idx=pkt.idx, seq=pkt.seq, rwin=self._rwin())
            self._send_ack(s, " (re-ACK)")
        else:
            self.net.emit("RECEIVER", "DISCARD", f"{pkt.name()} outside receiver window - ignored",
                          action="outside", idx=pkt.idx, seq=pkt.seq, rwin=self._rwin())


# --------------------------------------------------------------------------
# Run one simulation
# --------------------------------------------------------------------------
@dataclass
class Result:
    cfg: Config
    transmitted: int = 0
    retransmissions: int = 0
    delivered_ok: int = 0
    correct: bool = False
    sim_time_ms: float = 0.0
    throughput_kbps: float = 0.0
    utilization: float = 0.0
    wall_s: float = 0.0
    timeouts: int = 0
    acks_sent: int = 0
    aborted: bool = False
    counters: dict = field(default_factory=dict)
    lines: list = field(default_factory=list)
    events: list = field(default_factory=list)


def simulate(cfg: Config, echo=False) -> Result:
    cfg.validate()
    net = Net(cfg, echo=echo)
    data = [make_payload(i, cfg.pkt_bytes) for i in range(cfg.packets)]
    if cfg.protocol == "gbn":
        sender, receiver = GBNSender(net, data), GBNReceiver(net)
    else:
        sender, receiver = SRSender(net, data), SRReceiver(net)

    t0 = time.perf_counter()
    aborted = False
    sender.pump()
    while net._q and not sender.done:
        when, _, kind, args = heapq.heappop(net._q)
        if when > cfg.max_time_ms:
            aborted = True
            break
        net.t = when
        if kind == "to_R":
            receiver.on_packet(*args)
        elif kind == "to_S":
            sender.on_ack(*args)
        elif kind == "timer":
            sender.on_timeout(*args)
    wall = time.perf_counter() - t0

    ok = sum(1 for i, d in enumerate(receiver.delivered) if i < len(data) and d == data[i])
    res = Result(cfg=cfg)
    res.transmitted = net.stats["data_tx"]
    res.retransmissions = net.stats["retx"]
    res.delivered_ok = ok
    res.correct = (ok == cfg.packets and len(receiver.delivered) == cfg.packets)
    res.sim_time_ms = net.t
    res.aborted = aborted or not sender.done
    res.timeouts = net.stats["timeouts"]
    res.acks_sent = net.stats["acks_sent"]
    if net.t > 0:
        res.throughput_kbps = ok * cfg.pkt_bytes * 8 / net.t          # bits per ms == kbit/s
        res.utilization = (ok * cfg.tx_ms) / net.t                    # fraction of link busy with useful data
    res.wall_s = wall
    res.counters = dict(net.stats)
    res.lines, res.events = net.lines, net.events
    return res


def summary_text(res: Result) -> str:
    c = res.cfg
    c_ = res.counters
    out = [
        "=" * 72,
        f"SUMMARY  protocol={c.protocol.upper()}  packets={c.packets}  N={c.window}  k={c.seq_bits} "
        f"(seq 0..{c.modulus - 1})  seed={c.seed}",
        f"channel: loss={c.loss} corrupt={c.corrupt} delay={c.delay}  timeout={c.timeout_ms:.0f} ms",
        "-" * 72,
        f"data packets transmitted (incl. retx) : {res.transmitted}",
        f"retransmissions                        : {res.retransmissions}",
        f"timeouts                               : {res.timeouts}",
        f"ACKs sent by receiver                  : {res.acks_sent}",
        f"channel: data lost/corrupted           : {c_.get('data_lost', 0)}/{c_.get('data_corrupted', 0)}"
        f"   ACK lost/corrupted: {c_.get('ack_lost', 0)}/{c_.get('ack_corrupted', 0)}"
        f"   delayed: {c_.get('delayed', 0)}",
        f"packets delivered correctly, in order  : {res.delivered_ok} / {c.packets}"
        f"   (end-to-end check: {'PASS' if res.correct else 'FAIL'})",
        f"completion time (simulated)            : {res.sim_time_ms / 1000:.3f} s",
        f"throughput (goodput)                   : {res.throughput_kbps:.2f} kbit/s"
        f"   link utilisation: {res.utilization * 100:.2f} %",
        f"wall-clock execution time              : {res.wall_s * 1000:.1f} ms",
    ]
    if res.aborted:
        out.append("!! run aborted before all packets were acknowledged (max simulated time reached)")
    out.append("=" * 72)
    return "\n".join(out)


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="GBN / SR over a simulated unreliable link",
                                formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--protocol", choices=["gbn", "sr"], default="gbn")
    p.add_argument("--packets", type=int, default=200, help="number of data packets")
    p.add_argument("--window", type=int, default=4, help="window size N")
    p.add_argument("--seq-bits", type=int, default=3, help="k: sequence numbers 0..2^k-1")
    p.add_argument("--loss", type=float, default=0.0, help="loss probability (data and ACKs)")
    p.add_argument("--corrupt", type=float, default=0.0, help="corruption probability (data and ACKs)")
    p.add_argument("--delay", type=float, default=0.0, help="probability a packet is delayed")
    p.add_argument("--delay-min", type=float, default=20.0, help="min extra delay in ms")
    p.add_argument("--delay-max", type=float, default=100.0, help="max extra delay in ms")
    p.add_argument("--reorder", action="store_true", help="allow delayed packets to be overtaken (non-FIFO channel)")
    p.add_argument("--timeout", type=float, default=800.0, help="retransmission timeout in ms")
    p.add_argument("--seed", type=int, default=810, help="random seed (last 4 digits of roll no: 0810)")
    p.add_argument("--drop-first", type=int, nargs="*", default=[],
                   help="scripted loss: drop the FIRST transmission of these packet numbers")
    p.add_argument("--log", default=None, help="also write the full event log to this file")
    p.add_argument("--quiet", action="store_true", help="do not print the per-event log, only the summary")
    return p.parse_args(argv)


def main(argv=None):
    a = parse_args(argv)
    cfg = Config(protocol=a.protocol, packets=a.packets, window=a.window, seq_bits=a.seq_bits,
                 loss=a.loss, corrupt=a.corrupt, delay=a.delay, delay_min_ms=a.delay_min,
                 delay_max_ms=a.delay_max, timeout_ms=a.timeout, seed=a.seed, reorder=a.reorder,
                 drop_first=tuple(a.drop_first))
    try:
        cfg.validate()
    except ValueError as e:
        sys.exit(f"error: {e}")
    if cfg.protocol == "sr" and cfg.window > cfg.modulus // 2:
        print(f"WARNING: SR window {cfg.window} > 2^(k-1) = {cfg.modulus // 2}: sequence-number "
              f"ambiguity is possible (see report, Task 5).  Watch the end-to-end check.", file=sys.stderr)
    res = simulate(cfg, echo=not a.quiet)
    summary = summary_text(res)
    print(summary)
    if a.log:
        with open(a.log, "w") as f:
            f.write("\n".join(res.lines) + "\n" + summary + "\n")
    return 0 if res.correct else 1


if __name__ == "__main__":
    sys.exit(main())
