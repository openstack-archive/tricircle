from nova.exception import NovaException
from nova.i18n import _


class GlanceSyncException(NovaException):
    msg_fmt = _("Sync image failed: %(reason)s")
