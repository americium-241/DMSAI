from decentraflow import NodeBlueprint
from dmsai_models import init_db
from src.ocr_logic import process_document

init_db()

node = NodeBlueprint(
    node_name="ocr_node",
    process_func=process_document,
    config_dir="config",
    log_dir="logs",
)

app = node.app

# To run: uvicorn main:app --port 8013
