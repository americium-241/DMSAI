from decentraflow import NodeBlueprint
from dmsai_models import init_db
from src.classification_logic import process_classification

init_db()

node = NodeBlueprint(
    node_name="classification_node",
    process_func=process_classification,
    config_dir="config",
    log_dir="logs",
)

app = node.app
logger = node.logger


# To run: uvicorn main:app --port 8016
