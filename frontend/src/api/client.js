/**
 * API client.
 *
 * Every request goes to OUR Flask backend. The browser never calls
 * Open-Meteo directly: that would leak our usage pattern to a third
 * party, blow through the upstream rate limit on every map pan, and
 * make caching impossible.
 */

const BASE = import.meta.env.VITE_API_BASE ?? "";

class ApiError extends Error {
  constructor(message, status, body) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

async function request(path, options = {}) {
  const { timeout = 30000, ...rest } = options;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);

  try {
    const res = await fetch(`${BASE}${path}`, {
      headers: { "Content-Type": "application/json", ...(rest.headers ?? {}) },
      signal: controller.signal,
      ...rest,
    });

    const text = await res.text();
    let body = null;
    try {
      body = text ? JSON.parse(text) : null;
    } catch {
      body = { raw: text.slice(0, 500) };
    }

    if (!res.ok) {
      throw new ApiError(
        body?.message || body?.error || `Request failed (${res.status})`,
        res.status,
        body,
      );
    }
    return body;
  } catch (err) {
    if (err.name === "AbortError") {
      throw new ApiError("The request timed out.", 408, null);
    }
    if (err instanceof ApiError) throw err;
    throw new ApiError(
      "Cannot reach the API. Is the Flask server running? Check API_PORT in .env.",
      0,
      null,
    );
  } finally {
    clearTimeout(timer);
  }
}

export const api = {
  health: () => request("/health"),
  modelInfo: () => request("/model-info"),
  cities: () => request("/api/cities"),
  legend: () => request("/api/legend"),
  stats: () => request("/api/stats"),
  forecast: (horizon = 24) =>
    request(`/api/forecast?horizon=${encodeURIComponent(horizon)}`, {
      timeout: 60000,
    }),
  history: (cityId, days = 7) =>
    request(`/api/history/${encodeURIComponent(cityId)}?days=${days}`),
  predict: (cities) =>
    request("/predict", {
      method: "POST",
      body: JSON.stringify({ cities }),
    }),
};

export { ApiError };
