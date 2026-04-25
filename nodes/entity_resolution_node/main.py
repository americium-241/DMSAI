from decentraflow import NodeBlueprint
from src.entity_resolution_logic import process_entity_resolution
from dmsai_models import init_db

init_db()

node = NodeBlueprint(
    node_name="entity_resolution_node",
    process_func=process_entity_resolution,
    config_dir="config",
    log_dir="logs",
)

app = node.app

# To run: uvicorn main:app --port 8017
