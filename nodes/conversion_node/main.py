from decentraflow import NodeBlueprint
from src.conversion_logic import process_document

node = NodeBlueprint(
    node_name="conversion_node",
    process_func=process_document,
    config_dir="config",
    log_dir="logs",
)

app = node.app

# To run: uvicorn main:app --port 8011
