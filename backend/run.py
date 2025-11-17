import uvicorn

def start():
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=5601,
        reload=True,
        reload_excludes=["venv/*", "*.log"]
    )

if __name__ == "__main__":
    start()
