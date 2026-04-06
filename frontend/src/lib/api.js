const isBrowser = typeof window !== "undefined";
const isLocalDevelopment =
  isBrowser &&
  ["localhost", "127.0.0.1"].includes(window.location.hostname);

const API_BASE_URL = isLocalDevelopment
  ? (process.env.REACT_APP_BACKEND_URL || "http://localhost:8001").replace(/\/+$/, "")
  : "";

export const API = `${API_BASE_URL}/api`;
export { API_BASE_URL };
