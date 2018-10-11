from requests_client.utils import Enum


class LEAD_FILTER_BY_TASKS(Enum):
    EMPTY = 1
    UNCOMPLETED = 2


class LEAD_STATUS(Enum):
    # Pipelines may have custom statuses, but these are required
    SUCCESS = 142
    FAIL = 143


class ELEMENT_TYPE(Enum):
    # ENTITY_TYPE will be better name, but stick to amocrm terms
    # https://www.amocrm.ru/developers/content/api/notes#element_types
    CONTACT = 1
    LEAD = 2
    COMPANY = 3
    TASK = 4
    CUSTOMER = 12


class TASK_TYPE(Enum):
    # https://www.amocrm.ru/developers/content/api/tasks#type
    CALL = 1
    MEETING = 2
    LETTER = 3


class NOTE_TYPE(Enum):
    # https://www.amocrm.ru/developers/content/api/notes#note_types
    DEAL_CREATED = 1
    CONTACT_CREATED = 2
    DEAL_STATUS_CHANGED = 3
    COMMON = 4
    CALL_IN = 10
    CALL_OUT = 11
    COMPANY_CREATED = 12
    TASK_RESULT = 13
    SYSTEM = 25
    SMS_IN = 102
    SMS_OUT = 103


class FIELD_TYPE(Enum):
    # https://www.amocrm.ru/developers/content/api/custom_fields
    TEXT = 1
    NUMERIC = 2
    CHECKBOX = 3
    SELECT = 4
    MULTISELECT = 5
    DATE = 6
    URL = 7
    MULTITEXT = 8
    TEXTAREA = 9
    RADIOBUTTON = 10
    STREETADDRESS = 11
    SMART_ADDRESS = 13
    BIRTHDAY = 14
    legal_entity = 15
    ITEMS = 16
