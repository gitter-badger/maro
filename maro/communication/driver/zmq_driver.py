# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import socket
from typing import Dict

# third party package
import zmq

# private package
from maro.communication import AbsDriver, Message
from maro.communication.utils import default_parameters
from maro.utils import DummyLogger
from maro.utils.exception.communication_exception import PeersConnectionError, DriverReceiveError, DriverSendError, \
    SocketTypeError


PROTOCOL = default_parameters.driver.zmq.protocol
SEND_TIMEOUT = default_parameters.driver.zmq.send_timeout
RECEIVE_TIMEOUT = default_parameters.driver.zmq.receive_timeout


class ZmqDriver(AbsDriver):
    """The communication driver based on ZMQ.
    
    Args:
        protocol (str): underlying transport-layer protocol for transferring messages,
        send_timeout (int): The timeout in milliseconds for sending message. If -1, no timeout (infinite),
        receive_timeout (int): The timeout in milliseconds for receiving message. If -1, no timeout (infinite),
        logger: logger instance or DummyLogger.
    """

    def __init__(self, protocol: str = PROTOCOL, send_timeout: int = SEND_TIMEOUT,
                 receive_timeout: int = RECEIVE_TIMEOUT, logger=DummyLogger()):
        self._protocol = protocol
        self._send_timeout = send_timeout
        self._receive_timeout = receive_timeout
        self._ip_address = socket.gethostbyname(socket.gethostname())
        self._zmq_context = zmq.Context()
        self._logger = logger

        self._setup_sockets()

    def _setup_sockets(self):
        """
        Setup three kinds of sockets, and one poller.
            unicast_receiver: the zmq.PULL socket, use for receiving message from one-to-one communication,
            broadcast_sender: the zmq.PUB socket, use for broadcasting message to all subscribers,
            broadcast_receiver: the zmq.SUB socket, use for listening message from broadcast.

            poller: the zmq output multiplexing, use for receiving message from zmq.PULL socket and zmq.SUB socket.
        """
        self._unicast_receiver = self._zmq_context.socket(zmq.PULL)
        unicast_receiver_port = self._unicast_receiver.bind_to_random_port(f"{self._protocol}://*")
        self._logger.debug(f"Receive message via unicasting at {self._ip_address}:{unicast_receiver_port}.")

        # Dict about zmq.PUSH sockets, fulfills in self.connect.
        self._unicast_sender_dict = {}

        self._broadcast_sender = self._zmq_context.socket(zmq.PUB)
        self._broadcast_sender.setsockopt(zmq.SNDTIMEO, self._send_timeout)

        self._broadcast_receiver = self._zmq_context.socket(zmq.SUB)
        self._broadcast_receiver.setsockopt_string(zmq.SUBSCRIBE, "")
        broadcast_receiver_port = self._broadcast_receiver.bind_to_random_port(f"{self._protocol}://*")
        self._logger.debug(f"Subscriber message at {self._ip_address}:{broadcast_receiver_port}.")

        # record own sockets' address
        self._address = {zmq.PULL: f"{self._protocol}://{self._ip_address}:{unicast_receiver_port}",
                         zmq.SUB: f"{self._protocol}://{self._ip_address}:{broadcast_receiver_port}"}

        self._poller = zmq.Poller()
        self._poller.register(self._unicast_receiver, zmq.POLLIN)
        self._poller.register(self._broadcast_receiver, zmq.POLLIN)

    @property
    def address(self) -> Dict[int, str]:
        """ 
        address Dict[int, str]: own sockets' address.
            i.e. Dict[zmq.PULL, 'tcp://0.0.0.0:1234']
        """
        return self._address

    def connect(self, peers_address_dict: Dict[str, Dict[str, str]]):
        """
        Build a connection with all peers in peers socket address, and set up unicast sender which is zmq.PUSH socket
        for each peer.
        
        Args:
            peers_address_dict (Dict[str, Dict[str, str]]): Peers' socket address dict,
                the key of dict is the peer's name, 
                the value of dict is the peer's socket connection address stored in dict.
            i.e. Dict['peer1', Dict[zmq.PULL, 'tcp://0.0.0.0:1234']].
        """
        for peer_name, address_dict in peers_address_dict.items():
            for socket_type, address in address_dict.items():
                try:
                    if int(socket_type) == zmq.PULL:
                        self._unicast_sender_dict[peer_name] = self._zmq_context.socket(zmq.PUSH)
                        self._unicast_sender_dict[peer_name].setsockopt(zmq.SNDTIMEO, self._send_timeout)
                        self._unicast_sender_dict[peer_name].connect(address)
                        self._logger.debug(f"Connects to {peer_name} via unicasting.")
                    elif int(socket_type) == zmq.SUB:
                        self._broadcast_sender.connect(address)
                        self._logger.debug(f"Connects to {peer_name} via broadcasting.")
                    else:
                        raise SocketTypeError(f"Unrecognized socket type {socket_type}.")
                except Exception as e:
                    raise PeersConnectionError(f"Driver cannot connect to {peer_name}! Due to {str(e)}")

    def receive(self, is_continuous: bool = True):
        """
        Receive message from zmq.POLLER.

        Args:
            is_continuous (bool): Continuously receive message or not. Default is True.
        """
        while True:
            try:
                sockets = dict(self._poller.poll(self._receive_timeout))
            except Exception as e:
                raise DriverReceiveError(f"Driver cannot receive message as {e}")

            if self._unicast_receiver in sockets:
                recv_message = self._unicast_receiver.recv_pyobj()
                self._logger.debug(f"Receive a message from {recv_message.source} through unicast receiver.")
            else:
                recv_message = self._broadcast_receiver.recv_pyobj()
                self._logger.debug(f"Receive a message from {recv_message.source} through broadcast receiver.")

            yield recv_message

            if not is_continuous:
                break

    def send(self, message: Message):
        """
        Send message.

        Args:
            message (class): message to be sent.
        """
        try:
            self._unicast_sender_dict[message.destination].send_pyobj(message)
            self._logger.debug(f"Send a {message.tag} message to {message.destination}.")
        except Exception as e:
            return DriverSendError(f"Failure to send message caused by: {e}")

    def broadcast(self, message: Message):
        """
        Broadcast message.

        Args:
            message(class): message to be sent.
        """
        try:
            self._broadcast_sender.send_pyobj(message)
            self._logger.debug(f"Broadcast a {message.tag} message to all subscribers.")
        except Exception as e:
            return DriverSendError(f"Failure to broadcast message caused by: {e}")
