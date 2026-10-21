# Results table (200 packets, N = 4, k = 3, timeout = 800 ms, seed = 810)

| Scenario | Protocol | Packets transmitted | Retransmissions | Delivered correctly (of 200) | Sim. time (s) | Throughput (kbit/s) | Link util. (%) | Run time (ms) |
|---|---|---|---|---|---|---|---|---|
| A: Reliable | GBN | 200 | 0 | 200 | 25.21 | 63.46 | 3.17 | 47.8 |
| A: Reliable | SR | 200 | 0 | 200 | 25.21 | 63.46 | 3.17 | 74.3 |
| B: Loss 0.10 | GBN | 260 | 60 | 200 | 41.36 | 38.69 | 1.93 | 49.9 |
| B: Loss 0.10 | SR | 233 | 33 | 200 | 42.26 | 37.86 | 1.89 | 44.8 |
| C: Mixed errors | GBN | 264 | 64 | 200 | 42.32 | 37.80 | 1.89 | 74.9 |
| C: Mixed errors | SR | 231 | 31 | 200 | 42.56 | 37.59 | 1.88 | 44.5 |

Throughput = correctly delivered bits / simulated completion time. Run time = wall-clock time of the simulation program.
