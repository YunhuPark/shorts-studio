import path from "node:path";

// The API for the browser tests runs with the repository's virtualenv, whose layout differs per operating system.
export const PYTHON =
  process.platform === "win32" ? path.join("..", ".venv", "Scripts", "python.exe") : path.join("..", ".venv", "bin", "python");
export const E2E_SERVER = path.join("..", "tests", "e2e_server.py");
