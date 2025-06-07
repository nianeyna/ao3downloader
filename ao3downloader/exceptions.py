"""Custom exceptions go here."""


class Ao3DownloaderException(Exception):
    pass


class TimeoutException(Ao3DownloaderException):
    pass


class LockedException(Ao3DownloaderException):
    pass


class DeletedException(Ao3DownloaderException):
    pass


class ProceedException(Ao3DownloaderException):
    pass


class DownloadException(Ao3DownloaderException):
    pass


class LoginException(Ao3DownloaderException):
    pass


class InvalidLinkException(Ao3DownloaderException):
    pass


class InvalidStatusCodeException(Ao3DownloaderException):
    pass
