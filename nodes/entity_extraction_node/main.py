from decentraflow import NodeBlueprint
from src.entity_extraction_logic import process_entity_extraction
from dmsai_models import init_db

init_db()

node = NodeBlueprint(
    node_name="entity_extraction_node",
    process_func=process_entity_extraction,
    config_dir="config",
    log_dir="logs",
)

app = node.app

# To run: uvicorn main:app --port 8015
