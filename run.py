import uvicorn
from ocs_ai.config import Settings
from ocs_ai.app import create_app

if __name__ == "__main__":
    settings = Settings.load()
    uvicorn.run(create_app(settings), host="127.0.0.1", port=settings.port, access_log=False)
