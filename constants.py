import re

RE_STRUCT = re.compile(r"type (.*) struct")
RE_MAP = re.compile(r"map\[(.*)\](.*)")
RE_WEBHOOK = re.compile(r"webhooks?.go")