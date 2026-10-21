# CN Assignment-II 

Name: Bashair | Roll No: 24K-0810 | Random seed: 0810

## How to run

```
python transport.py --protocol sr --packets 200 --window 4 --seq-bits 3 --loss 0.05 --corrupt 0.05 --delay 0.10 --timeout 800 --seed 810 --quiet
```

Remove `--quiet` to print one log line for every send, receive, ACK, loss, corruption, delay,
timeout and retransmission. Add `--log run.log` to save the log and summary to a file.
Exit code is 0 only if all packets were delivered correctly and in order.

### Parameters (`python transport.py --help`)

| Option | Default | Meaning |
|---|---|---|
| `--protocol gbn|sr` | gbn | protocol |
| `--packets` | 200 | number of data packets |
| `--window` | 4 | window size N (max 2^k - 1; SR is only safe up to 2^(k-1), a warning is printed above that) |
| `--seq-bits` | 3 | k: sequence numbers 0..2^k-1, wrap modulo 2^k |
| `--loss` | 0.0 | loss probability (data and ACKs) |
| `--corrupt` | 0.0 | corruption probability (data and ACKs), detected by a 16-bit checksum |
| `--delay` | 0.0 | probability a packet or ACK gets an extra delay |
| `--delay-min / --delay-max` | 20 / 100 ms | range of the extra delay |
| `--timeout` | 800 ms | retransmission timeout (worst-case RTT is about 712 ms) |
| `--seed` | 810 | random seed |
| `--reorder` | off | allow delayed packets to be overtaken (default channel is FIFO) |
| `--drop-first 2 5` | none | scripted loss of the first transmission of packets 2 and 5 |
| `--log FILE`, `--quiet` | | logging options |

## Reproduce every deliverable

| Task | Command | Output |
|---|---|---|
| Task 2 traces | `python task2_trace.py` | `traces/task2_gbn_trace.md`, `traces/task2_sr_trace.md`, full logs in `traces/` |
| Task 2 by hand | `python transport.py --protocol gbn --packets 10 --window 4 --seq-bits 4 --drop-first 2` (also `--protocol sr`) | full event log |
| Task 4 experiments | `python experiments.py --seeds 30` | `results_table.md`, `results.csv`, `gbn_vs_sr.png`, `results_multiseed.csv`, `logs/` |
| Sequence-number ambiguity | `python transport.py --protocol sr --window 5 --seq-bits 3 --loss 0.2 --quiet` | end-to-end check prints FAIL |

## Files

- `transport.py` - simulator: channel, checksum, GBN sender/receiver, SR sender/receiver, CLI
- `experiments.py` - experiment
- `results_table.md`, `results.csv`, `gbn_vs_sr.png` - results table and the GBN vs SR graph
- `Assignment 2 - report.docx` - report (3 pages): approach, Tasks 1, 2, 4, 5, comparison, conclusion
- `logs/` - the event logs of the six experiment runs

## Assumptions

- Link: R = 2 Mbps, RTT = 500 ms, L = 1000 bytes, so one packet takes 4 ms to send and one-way propagation is 250 ms. ACK serialisation time is ignored.
- Loss, corruption and delay apply to data packets and ACKs alike. Corruption flips one random bit; a corrupt packet or ACK is treated as not received.
- Delay is bounded and the channel is FIFO by default. The timeout (800 ms) is above the worst-case RTT, so no timeout fires prematurely (maximum-packet-lifetime assumption for k-bit sequence numbers).
- `base` and `nextseqnum` are absolute counters inside the sender; the number sent on the wire is the counter mod 2^k (logs show both, e.g. `base=9(s1)`).
- The GBN receiver sends no ACK until the first packet has been delivered.
- Every run ends with an end-to-end check (all packets delivered in order with identical content).
- A "scripted" drop (`--drop-first`) is used only to reproduce the fixed Task 2 scenario.
