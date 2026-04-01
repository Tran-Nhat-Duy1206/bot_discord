module.exports = {
  apps: [
    {
      name: "discord-bot",
      script: "main.py",
      interpreter: ".\\.venv\\Scripts\\python.exe",
      cwd: "E:\\Code\\discord-bot",
      env: {
        PYTHONUNBUFFERED: "1"
      }
    }
  ]
}