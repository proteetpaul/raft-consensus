# raftos
Raft Consensus implementation for Distributed Systems(CS60002) for Spring 2022.

#### Group Members:
- Tushar Gupta (18CS30044)
- Mayank Raj (18CS30028)
- Ashish Gour (18CS30008)
- Proteet Paul (18CS10065)

Asynchronous replication framework based on Raft Algorithm for fault-tolerant distributed systems.

#### Install

```
pip install raftos
```

#### Register nodes on every server

```python
import raftos
loop.create_task(
    raftos.register(
        # node running on this machine
        '127.0.0.1:8000',

        # other servers
        cluster=[
            '127.0.0.1:8001',
            '127.0.0.1:8002'
        ]
    )
)
loop.run_forever()
```

#### Data replication

```python
counter = raftos.Replicated(name='counter')
data = raftos.ReplicatedDict(name='data')
# value on a leader gets replicated to all followers
await counter.set(42)
await data.update({
    'id': 337,
    'data': {
        'amount': 20000,
        'created_at': '7/11/16 18:45'
    }
})
```

<!-- #### In case you only need consensus algorithm with leader election

```python
await raftos.wait_until_leader(current_node)
```
or
```python
if raftos.get_leader() == current_node:
    # make request or respond to a client
```
or
```python
raftos.configure({
    'on_leader': start,
    'on_follower': stop
})
``` -->
Whenever the leader falls, someone takes its place.
