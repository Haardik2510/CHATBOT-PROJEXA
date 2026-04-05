const API_BASE_URL =
  process.env.REACT_APP_BACKEND_URL ||
  process.env.REACT_APP_API_URL ||
  "http://localhost:8001";

export const API = `${API_BASE_URL}/api`;
export { API_BASE_URL };
