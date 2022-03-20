import base64
from .log import logger

class BaseCryptor:
    def __init__(self, config):
        self.config = config

    def encrypt(self, data):
        return data

    def decrypt(self, data):
        return data

    def get_config(self):
        return self.config
    def set_config(self, config):
        self.config = config

default_cryptor = BaseCryptor

try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    class Cryptor(BaseCryptor):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)

            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=self.config.salt,
                iterations=100000,
                backend=default_backend()
            )
            self.f = Fernet(base64.urlsafe_b64encode(kdf.derive(self.config.secret_key)))

        def encrypt(self, data):
            return self.f.encrypt(data)

        def decrypt(self, data):
            return self.f.decrypt(data)

    default_cryptor = Cryptor

except ImportError:
    logger.warning('cryptography is not installed!')


# from .cryptors import default_cryptor
from .serializers import MessagePackSerializer


class Configuration:
    def __init__(self):
        self.configure(self.default_settings())

    @staticmethod
    def default_settings():
        return {
            'log_path': '/var/log/raftos/',
            'serializer': MessagePackSerializer,

            'heartbeat_interval': 0.3,

            # Leader will step down if it doesn't have a majority of follower's responses
            # for this amount heartbeats
            'step_down_missed_heartbeats': 5,

            # Randomized election timeout
            # [step_down_missed_heartbeats, M * step_down_missed_heartbeats]
            'election_interval_spread': 3,

            # For UDP messages encryption
            'secret_key': b'raftos sample secret key',
            'salt': b'raftos sample salt',
            'cryptor': default_cryptor,

            # Election callbacks
            'on_leader': lambda: None,
            'on_follower': lambda: None,

            # network details
            'serial_no': 1,
            'network_address': 127.0.0.1,
            'network_name': 'localhost'
        }

    def configure(self, kwargs):
        for param, value in kwargs.items():
            setattr(self, param.lower(), value)

        self.step_down_interval = self.heartbeat_interval * self.step_down_missed_heartbeats
        self.election_interval = (
            self.step_down_interval,
            self.step_down_interval * self.election_interval_spread
        )

        if isinstance(self.cryptor, type):
            self.cryptor = self.cryptor(self)


config = Configuration()
configure = config.configure
