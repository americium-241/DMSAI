from decentraflow import NodeBlueprint
from src.field_extraction_logic import process_field_extraction
from dmsai_models import init_db

init_db()

node = NodeBlueprint(
    node_name="field_extraction_node",
    process_func=process_field_extraction,
    config_dir="config",
    log_dir="logs",
)

app = node.app

# To run: uvicorn main:app --port 8018
