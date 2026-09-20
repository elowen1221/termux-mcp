from termux_mcp.config_schema import CONFIG_SCHEMA_VERSION
def test_config_schema_is_positive_integer():
    assert isinstance(CONFIG_SCHEMA_VERSION,int) and CONFIG_SCHEMA_VERSION>=1
