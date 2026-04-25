from decentraflow import NodeBlueprint
from src.embedding_logic import process_embedding
from dmsai_models import init_db

init_db()

node = NodeBlueprint(
    node_name="embedding_node",
    process_func=process_embedding,
    config_dir="config",
    log_dir="logs",
)

app = node.app

# To run: uvicorn main:app --port 8014
