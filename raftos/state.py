import asyncio
import functools
import random
import time

from .conf import config
from .exceptions import NotALeaderException
from .storage import FileStorage, Log, StateMachine
from .timer import Timer


def validate_term(func):
    """Compares current term and request term:
        if current term is stale(means current term of a server < the recieved term of the peer):
            update current term & become follower
        if received term is stale(means current term of a server > the recieved term from the peer)::
            respond with False
    """

    @functools.wraps(func)
    def on_receive_function(self, data):
        if self.storage.term < data['term']:
            self.storage.update({
                'term': data['term']
            })
            if not isinstance(self, Follower):
                self.state.to_follower()

        if self.storage.term > data['term'] and not data['type'].endswith('_response'):
            response = {
                'type': '{}_response'.format(data['type']),
                'term': self.storage.term,
                'success': False
            }
            asyncio.ensure_future(self.state.send(response, data['sender']), loop=self.loop)
            return

        return func(self, data)
    return on_receive_function


def validate_commit_index(func):
    """Apply to State Machine everything up to commit index"""

    @functools.wraps(func)
    def wrapped(self, *args, **kwargs):
        for not_applied in range(self.log.last_applied + 1, self.log.commit_index + 1):
            self.state_machine.apply(self.log[not_applied]['command'])
            self.log.last_applied += 1

            try:
                self.apply_future.set_result(not_applied)
            except (asyncio.futures.InvalidStateError, AttributeError):
                pass

        return func(self, *args, **kwargs)
    return wrapped
recieverid=0










#A Class for each node in the system, leader, candidate or follower
class BaseState:
    def __init__(self, state):
        self.state = state

        self.id = self.state.id
        self.loop = self.state.loop

        self.storage = self.state.storage
        self.log = self.state.log
        self.state_machine = self.state.state_machine

    @validate_term
    def on_receive_request_vote(self, data):
        """RequestVote RPC — invoked by Candidate to gather votes
        Arguments:
            term — candidate’s term
            candidate_id — candidate requesting vote
            last_log_index — index of candidate’s last log entry
            last_log_term — term of candidate’s last log entry
        Results:
            term — for candidate to update itself
            vote_granted — True means candidate received vote
        Receiver implementation:
            1. Reply False if term < self term
            2. If voted_for is None or candidateId ????,
            and candidate’s log is at least as up-to-date as receiver’s log, grant vote
        """

    @validate_term
    def on_receive_request_vote_response(self, data):
        """RequestVote RPC response — description above"""

    @validate_term
    def on_receive_append_entries(self, data):
        """AppendEntries RPC — replicate log entries / heartbeat
        Arguments:
            term — leader’s term
            leader_id — so follower can redirect clients
            prev_log_index — index of log entry immediately preceding new ones
            prev_log_term — term of prev_log_index entry
            entries[] — log entries to store
            commit_index — leader’s commit_index
        Results:
            term — for leader to update itself
            success — True if follower contained entry matching prev_log_index and prev_log_term
        Receiver implementation:
            1. Reply False if term < self term
            2. Reply False if log entry term at prev_log_index doesn't match prev_log_term
            3. If an existing entry conflicts with a new one, delete the entry and following entries
            4. Append any new entries not already in the log
            5. If leader_commit > commit_index, set commit_index = min(leader_commit, index of last new entry)
        """

    @validate_term
    def on_receive_append_entries_response(self, data):
        """AppendEntries RPC response — description above"""
senderid=0





# Here we consider the heartbeats as empty AppendEntries RPCs to servers
class Leader(BaseState):
    """Raft Leader
    Upon election: send initial empty AppendEntries RPCs (heartbeat) to each server;
    repeat during idle periods to prevent election timeouts
    — If command received from client: append entry to local log, respond after entry applied to state machine
    - If last log index ≥ next_index for a follower: send AppendEntries RPC with log entries starting at next_index
    — If successful: update next_index and match_index for follower
    — If AppendEntries fails because of log inconsistency: decrement next_index and retry
    — If there exists an N such that N > commit_index, a majority of match_index[i] ≥ N,
    and log[N].term == self term: set commit_index = N
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.request_id = 0
        self.response_map = {}

        self.heartbeat_timer = Timer(config.heartbeat_interval, self.heartbeat)
        self.step_down_timer = Timer(config.step_down_missed_heartbeats * config.heartbeat_interval,self.state.to_follower)

    def start(self):
        self.init_log()
        self.heartbeat()
        self.heartbeat_timer.start()
        self.step_down_timer.start()

    def init_log(self):
        self.log.next_index = {
            follower: self.log.last_log_index + 1 for follower in self.state.cluster
        }

        self.log.match_index = {
            follower: 0 for follower in self.state.cluster
        }

    def stop(self):
        self.heartbeat_timer.stop()
        self.step_down_timer.stop()

    async def append_entries(self, destination=None):
        """AppendEntries RPC — replicate log entries / heartbeat
        Args:
            destination — destination id
        Request params:
            term — leader’s term
            leader_id — so follower can redirect clients
            prev_log_index — index of log entry immediately preceding new ones
            prev_log_term — term of prev_log_index entry
            commit_index — leader’s commit_index
            entries[] — log entries to store 
        """

        # Send AppendEntries RPC to destination if specified or broadcast to everyone(when destination = None)
        dest_list = [destination] if destination else self.state.cluster
        for dest in dest_list:
            data = {
                'type': 'append_entries',

                'term': self.storage.term,
                'leader_id': self.id,
                'commit_index': self.log.commit_index,

                'request_id': self.request_id
            }

            next_index = self.log.next_index[dest]
            prev_index = next_index - 1

            if self.log.last_log_index < next_index:
                data['entries'] = []

            else:
                data['entries'] = [self.log[next_index]]

            data.update({
                'prev_log_index': prev_index,
                'prev_log_term': self.log[prev_index]['term'] if self.log and prev_index else 0
            })

            asyncio.ensure_future(self.state.send(data, dest), loop=self.loop)

    @validate_commit_index
    @validate_term
    def on_receive_append_entries_response(self, data):
        s_id = self.state.get_sender_id(data['sender'])

        # Count all unqiue responses per particular heartbeat interval
        # and step down via <step_down_timer> if leader doesn't get majority of responses for
        # <step_down_missed_heartbeats> heartbeats

        if data['request_id'] in self.response_map:
            self.response_map[data['request_id']].add(s_id)

            if self.state.is_majority(len(self.response_map[data['request_id']]) + 1):
                self.step_down_timer.reset()
                del self.response_map[data['request_id']]

        if not data['success']:
            self.log.next_index[s_id] = max(self.log.next_index[s_id] - 1, 1)

        else:
            self.log.next_index[s_id] = data['last_log_index'] + 1
            self.log.match_index[s_id] = data['last_log_index']

            self.update_commit_index()

        # Send AppendEntries RPC to continue updating fast-forward log (data['success'] == False)
        # or in case there are new entries to sync (data['success'] == data['updated'] == True)
        if self.log.last_log_index >= self.log.next_index[s_id]:
            asyncio.ensure_future(self.append_entries(destination=s_id), loop=self.loop)

    def update_commit_index(self):
        commit_on_majority = 0
        for index in range(self.log.commit_index + 1, self.log.last_log_index + 1):
            commited_count = len([1 for follower in self.log.match_index if self.log.match_index[follower] >= index])

            # If index is matched on at least half + self for current term — commit
            # That may cause commit fails upon restart with stale logs
            is_current_term = self.log[index]['term'] == self.storage.term
            if self.state.is_majority(commited_count + 1) and is_current_term:
                commit_on_majority = index

            else:
                break

        if commit_on_majority > self.log.commit_index:
            self.log.commit_index = commit_on_majority

    async def execute_command(self, command):
        """Write to log & send AppendEntries RPC"""
        self.apply_future = asyncio.Future(loop=self.loop)

        entry = self.log.write(self.storage.term, command)
        asyncio.ensure_future(self.append_entries(), loop=self.loop)

        await self.apply_future

    def heartbeat(self):
        self.request_id += 1
        self.response_map[self.request_id] = set()
        asyncio.ensure_future(self.append_entries(), loop=self.loop)


class Candidate(BaseState):
    """Raft Candidate
    — On conversion to candidate, start election:
        — Increment self term
        — Vote for self
        — Reset election timer
        — Send RequestVote RPCs to all other servers
    — If votes received from majority of servers: become leader
    — If AppendEntries RPC received from new leader: convert to follower
    — If election timeout elapses: start new election
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.election_timer = Timer(self.election_interval, self.state.to_follower)
        self.vote_count = 0

    def start(self):
        """Increment current term, vote for herself & send vote requests"""
        self.storage.update({
            'term': self.storage.term + 1,
            'voted_for': self.id
        })

        self.vote_count = 1
        self.request_vote()
        self.election_timer.start()

    def request_vote(self):
        """RequestVote RPC — gather votes
        Arguments:
            term — candidate’s term
            candidate_id — candidate requesting vote
            last_log_index — index of candidate’s last log entry
            last_log_term — term of candidate’s last log entry
        """
        data = {
            'type': 'request_vote',

            'term': self.storage.term,
            'candidate_id': self.id,
            'last_log_index': self.log.last_log_index,
            'last_log_term': self.log.last_log_term
        }
        self.state.broadcast(data)

    def stop(self):
        self.election_timer.stop()

    @validate_term
    def on_receive_request_vote_response(self, data):
        """Receives response for vote request.
        If the vote was granted then check if we got majority and may become Leader
        """

        if data.get('vote_granted'):
            self.vote_count += 1

            if self.state.is_majority(self.vote_count):
                self.state.to_leader()

    @validate_term
    def on_receive_append_entries(self, data):
        """If we discover a Leader with the same term — step down"""
        if self.storage.term == data['term']:
            self.state.to_follower()

    @staticmethod
    def election_interval():
        return random.uniform(*config.election_interval)


class Follower(BaseState):
    """Raft Follower
    — Respond to RPCs from candidates and leaders
    — If election timeout elapses without receiving AppendEntries RPC from current leader
    or granting vote to candidate: convert to candidate
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.election_timer = Timer(self.election_interval, self.start_election)

    def start(self):
        self.init_storage()
        self.election_timer.start()

    def init_storage(self):
        """Set current term to zero upon initialization & voted_for to None"""
        if not self.storage.exists('term'):
            self.storage.update({
                'term': 0,
            })

        self.storage.update({
            'voted_for': None
        })

    def stop(self):
        self.election_timer.stop()

    @staticmethod
    def election_interval():
        return random.uniform(*config.election_interval)

    @validate_commit_index
    @validate_term
    def on_receive_append_entries(self, data):
        self.state.set_leader(data['leader_id'])

        # Reply False if log doesn’t contain an entry at prev_log_index whose term matches prev_log_term
        try:
            prev_log_index = data['prev_log_index']
            if prev_log_index > self.log.last_log_index or (prev_log_index and self.log[prev_log_index]['term'] != data['prev_log_term']):
                response = {
                    'type': 'append_entries_response',
                    'term': self.storage.term,
                    'success': False,

                    'request_id': data['request_id']
                }
                asyncio.ensure_future(self.state.send(response, data['sender']), loop=self.loop)
                return
        except IndexError:
            pass

        # If an existing entry conflicts with a new one (same index but different terms),
        # delete the existing entry and all that follow it
        new_index = data['prev_log_index'] + 1
        try:
            if self.log[new_index]['term'] != data['term'] or (
                self.log.last_log_index != prev_log_index
            ):
                self.log.erase_from(new_index)
        except IndexError:
            pass

        # It's always one entry for now
        for entry in data['entries']:
            self.log.write(entry['term'], entry['command'])

        # Update commit index if necessary
        if self.log.commit_index < data['commit_index']:
            self.log.commit_index = min(data['commit_index'], self.log.last_log_index)

        # Respond True since entry matching prev_log_index and prev_log_term was found
        response = {
            'type': 'append_entries_response',
            'term': self.storage.term,
            'success': True,

            'last_log_index': self.log.last_log_index,
            'request_id': data['request_id']
        }
        asyncio.ensure_future(self.state.send(response, data['sender']), loop=self.loop)

        self.election_timer.reset()

    @validate_term
    def on_receive_request_vote(self, data):
        if self.storage.voted_for is None and not data['type'].endswith('_response'):

            # Candidates' log has to be up-to-date

            # If the logs have last entries with different terms,
            # then the log with the later term is more up-to-date. If the logs end with the same term,
            # then whichever log is longer is more up-to-date.

            if data['last_log_term'] != self.log.last_log_term:
                up_to_date = data['last_log_term'] > self.log.last_log_term
            else:
                up_to_date = data['last_log_index'] >= self.log.last_log_index

            if up_to_date:
                self.storage.update({
                    'voted_for': data['candidate_id']
                })

            response = {
                'type': 'request_vote_response',
                'term': self.storage.term,
                'vote_granted': up_to_date
            }

            asyncio.ensure_future(self.state.send(response, data['sender']), loop=self.loop)

    def start_election(self):
        self.state.to_candidate()


def leader_required(func):

    @functools.wraps(func)
    async def wrapped(cls, *args, **kwargs):
        await cls.wait_for_election_success()
        if not isinstance(cls.leader, Leader):
            raise NotALeaderException(
                'Leader is {}!'.format(cls.leader or 'not chosen yet')
            )

        return await func(cls, *args, **kwargs)
    return wrapped


class State:
    """Abstraction layer between Server & Raft State and Storage/Log & Raft State"""

    # <Leader object> if state is leader
    # <state_id> if state is follower
    # <None> if leader is not chosen yet
    leader = None

    # Await this future for election ending
    leader_future = None

    # Node id that's waiting until it becomes leader and corresponding future
    wait_until_leader_id = None
    wait_until_leader_future = None

    def __init__(self, server):
        self.server = server
        self.id = self._get_id(server.host, server.port)
        self.__class__.loop = self.server.loop

        self.storage = FileStorage(self.id)
        self.log = Log(self.id)
        self.state_machine = StateMachine(self.id)

        self.state = Follower(self)

    def start(self):
        self.state.start()

    def stop(self):
        self.state.stop()

    @classmethod
    @leader_required
    async def get_value(cls, name):
        return cls.leader.state_machine[name]

    @classmethod
    @leader_required
    async def set_value(cls, name, value):
        await cls.leader.execute_command({name: value})

    def send(self, data, destination):
        return self.server.send(data, destination)

    def broadcast(self, data):
        """Sends request to all cluster excluding itself"""
        return self.server.broadcast(data)

    def request_handler(self, data):
        getattr(self.state, 'on_receive_{}'.format(data['type']))(data)

    @staticmethod
    def _get_id(host, port):
        return '{}:{}'.format(host, port)

    def get_sender_id(self, sender):
        return self._get_id(*sender)

    @property
    def cluster(self):
        return [self._get_id(*address) for address in self.server.cluster]

    def is_majority(self, count):
        return count > (self.server.cluster_count // 2)

    def to_candidate(self):
        self._change_state(Candidate)
        self.set_leader(None)

    def to_leader(self):
        self._change_state(Leader)
        self.set_leader(self.state)
        if asyncio.iscoroutinefunction(config.on_leader):
            asyncio.ensure_future(config.on_leader())
        else:
            config.on_leader()

    def to_follower(self):
        self._change_state(Follower)
        self.set_leader(None)
        if asyncio.iscoroutinefunction(config.on_follower):
            asyncio.ensure_future(config.on_follower())
        else:
            config.on_follower()

    def set_leader(self, leader):
        cls = self.__class__
        cls.leader = leader

        if cls.leader and cls.leader_future and not cls.leader_future.done():
            # We release the future when leader is elected
            cls.leader_future.set_result(cls.leader)

        if cls.wait_until_leader_id and (
            cls.wait_until_leader_future and not cls.wait_until_leader_future.done()
        ) and cls.get_leader() == cls.wait_until_leader_id:
            # We release the future when specific node becomes a leader
            cls.wait_until_leader_future.set_result(cls.leader)

    def _change_state(self, new_state):
        self.state.stop()
        self.state = new_state(self)
        self.state.start()

    @classmethod
    def get_leader(cls):
        if isinstance(cls.leader, Leader):
            return cls.leader.id

        return cls.leader

    @classmethod
    async def wait_for_election_success(cls):
        """Await this function if your cluster must have a leader"""
        if cls.leader is None:
            cls.leader_future = asyncio.Future(loop=cls.loop)
            await cls.leader_future

    @classmethod
    async def wait_until_leader(cls, node_id):
        """Await this function if you want to do nothing until node_id becomes a leader"""
        if node_id is None:
            raise ValueError('Node id can not be None!')

        if cls.get_leader() != node_id:
            cls.wait_until_leader_id = node_id
            cls.wait_until_leader_future = asyncio.Future(loop=cls.loop)
            await cls.wait_until_leader_future

            cls.wait_until_leader_id = None
            cls.wait_until_leader_future = None

if senderid != 0:
    """Raft Follower
    — Respond to RPCs from candidates and leaders
    — If election timeout elapses without receiving AppendEntries RPC from current leader
    or granting vote to candidate: convert to candidate
    """
    s = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    s.bind((socket.gethostname(),0))
    port = s.getsockname()[1]
    s.listen(50)
    timeout = 2000
    inputsockets = [s]
    t = os.fork()
    if  t==0:
        while True:
            rlist, wlist, xlist = select(inputsockets,[],[],timeout)
            if not rlist and not wlist and not xlist:
                s.close()
                sys.exit(0)
            for insock in rlist:
                if insock is s:
                    new_socket, addr = s.accept()
                    inputsockets.append(new_socket)      
                else:
                    data = insock.recv(1024)
                    if data:
                        print data
                        insock.close()
                        inputsockets.remove(insock)
    s = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    s.bind((socket.gethostname(),0))
    port = s.getsockname()[1]
    s.listen(50)
    timeout = 2000
    inputsockets = [s]
    t = os.fork()
    if  t==0:
        while True:
            rlist, wlist, xlist = select(inputsockets,[],[],timeout)
            if not rlist and not wlist and not xlist:
                s.close()
                sys.exit(0)
            for insock in rlist:
                if insock is s:
                    new_socket, addr = s.accept()
                    inputsockets.append(new_socket)      
                else:
                    data = insock.recv(1024)
                    if data:
                        print data
                        insock.close()
                        inputsockets.remove(insock)

if recieverid != 0
	emptyVal = -2
    heartBeat = -3
    voteRequest = -4
    acceptVoteRequest = -5
    rejectVoteRequest = -6
    heartBeatResponse = -7
    diedSuffix = 100
    myId = emptyVal
    currentValues = {}
    currentLeader = emptyVal
    acceptedHosts = Set([])
    respondedToHeartBeat = Set([])
    currentState = 0   # 0 for follower 1 for candidate 2 for leader
    leader = 2; candidate = 1; follower = 0;
    currentTerm = 0 # everyone starts in 0th term
    currentElectionRound = 0
    timeoutRangeMin = 150 # this is in millisecond
    timeoutRangeMax = 300 # this is in millisecond
    electionTimeout = 0 # this will be set in main for the first time
    heartBeatTimeout = 0 # useful only if I am leader
    votedForThisTerm = False
    votedFor = emptyVal


class Node(object):
    """
    A representation of any node in the network.
    The ID must uniquely identify a node. Node objects with the same ID will be treated as equal, i.e. as representing the same node.
    """

    def __init__(self, id, **kwargs):
        """
        Initialise the Node; id must be immutable, hashable, and unique.
        :param id: unique, immutable, hashable ID of a node
        :type id: any
        :param **kwargs: any further information that should be kept about this node
        """

        self._id = id
        for key in kwargs:
            setattr(self, key, kwargs[key])

    def __setattr__(self, name, value):
        if name == 'id':
            raise AttributeError('Node id is not mutable')
        super(Node, self).__setattr__(name, value)

    def __eq__(self, other):
        return isinstance(other, Node) and self.id == other.id

    def __ne__(self, other):
        # In Python 3, __ne__ defaults to inverting the result of __eq__.
        # Python 2 isn't as sane. So for Python 2 compatibility, we also need to define the != operator explicitly.
        return not (self == other)

    def __hash__(self):
        return hash(self.id)

    def __str__(self):
        return self.id

    def __repr__(self):
        v = vars(self)
        return '{}({}{})'.format(type(self).__name__, repr(self.id), (', ' + ', '.join('{} = {}'.format(key, repr(v[key])) for key in v if key != '_id')) if len(v) > 1 else '')

    def _destroy(self):
        pass
    @property
    def id(self):
        return self._id

class TCPNode(Node):
    """
    A node intended for communication over TCP/IP. Its id is the network address (host:port).
    """

    def __init__(self, address, **kwargs):
        """
        Initialise the TCPNode
        :param address: network address of the node in the format 'host:port'
        :type address: str
        :param **kwargs: any further information that should be kept about this node
        """

        super(TCPNode, self).__init__(address, **kwargs)
        self.__address = address
        self.__host, port = address.rsplit(':', 1)
        self.__port = int(port)
        #self.__ip = globalDnsResolver().resolve(self.host)

    @property
    def address(self):
        return self.__address

    @property
    def host(self):
        return self.__host

    @property
    def port(self):
        return self.__port

    def __repr__(self):
        v = vars(self)
        filtered = ['_id', '_TCPNode__address', '_TCPNode__host', '_TCPNode__port']
        formatted = ['{} = {}'.format(key, repr(v[key])) for key in v if key not in filtered]
        return '{}({}{})'.format(type(self).__name__, repr(self.id), (', ' + ', '.join(formatted)) if len(formatted) else '')

