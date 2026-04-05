const sanitizeApiBaseUrl = (value) => {
  const raw = (value || "").trim();
  if (!raw) {
    return "";
  }

  // Ignore malformed env values like "REACT_APP_BACKEND_URL=https://..."
  const normalized = raw.includes("=") ? raw.split("=").pop().trim() : raw;

  if (!/^https?:\/\//i.test(normalized)) {
    return "";
  }

  return normalized.replace(/\/+$/, "");
};

const API_BASE_URL =
  sanitizeApiBaseUrl(process.env.REACT_APP_BACKEND_URL) ||
  sanitizeApiBaseUrl(process.env.REACT_APP_API_URL) ||
  "https://chatbot-projexa.onrender.com";

export const API = `${API_BASE_URL}/api`;
export { API_BASE_URL };
