"""晓楠修仙最小核心公共入口。"""

from .data_files import (
    JsonDataCatalog as JsonDataCatalog,
    JsonDataError as JsonDataError,
    JsonDataReader as JsonDataReader,
    JsonDocument as JsonDocument,
    content_section as content_section,
)
from .database import Database as Database, record_exists as record_exists
from .utils import (
    elapsed_seconds as elapsed_seconds,
    require_user_id as require_user_id,
    utc_now as utc_now,
)
from .weighted_pool import inverse_weighted_choice as inverse_weighted_choice


CORE_VERSION = "xiaonan.minimal-core.v1"
