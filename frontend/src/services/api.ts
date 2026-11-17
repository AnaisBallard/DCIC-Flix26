import type { Movie, PageResult, Review, ReviewReceipt } from "../types";

const gatewayUrl = (import.meta.env.VITE_GATEWAY_URL || "http://localhost:8000").replace(/\/$/, "");

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${gatewayUrl}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch (error) {
    throw new Error("No se pudo conectar con el servidor. Comprueba que esté disponible.");
  }

  if (!response.ok) {
    let detail = `Error ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      // Some gateway errors do not include a JSON body.
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export interface MovieQuery {
  q?: string;
  genre?: string;
  page?: number;
  pageSize?: number;
}

export function getMovies(query: MovieQuery = {}) {
  const params = new URLSearchParams();
  if (query.q?.trim()) params.set("q", query.q.trim());
  if (query.genre) params.set("genre", query.genre);
  params.set("page", String(query.page ?? 1));
  params.set("page_size", String(query.pageSize ?? 20));
  return request<PageResult<Movie>>(`/api/movies?${params}`);
}

export function getMovie(movieId: string) {
  return request<Movie>(`/api/movies/${encodeURIComponent(movieId)}`);
}

export function getReviews(movieId: string, page = 1) {
  return request<PageResult<Review>>(
    `/api/movies/${encodeURIComponent(movieId)}/reviews?page=${page}&page_size=20`,
  );
}

export function submitReview(review: Omit<Review, "_id" | "date">) {
  return request<ReviewReceipt>("/api/interactions/reviews", {
    method: "POST",
    body: JSON.stringify(review),
  });
}

export function getHealth() {
  return request<{ status: string; services: Record<string, string> }>("/api/health");
}
