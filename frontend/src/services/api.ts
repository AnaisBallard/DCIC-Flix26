import type { Movie, PageResult, Review, ReviewReceipt } from "../types";

const gatewayUrl = (import.meta.env.VITE_GATEWAY_URL || "http://localhost:8000").replace(/\/$/, "");

type ApiMovie = Omit<Movie, "imdb"> & {
  imdb?: Omit<NonNullable<Movie["imdb"]>, "rating"> & { rating?: number | string };
};

function normalizeMovie(movie: ApiMovie): Movie {
  const rawRating = movie.imdb?.rating;
  const rating = typeof rawRating === "string"
    ? Number(rawRating.trim().replace(",", "."))
    : rawRating;

  return {
    ...movie,
    imdb: movie.imdb
      ? {
          ...movie.imdb,
          rating: typeof rating === "number" && Number.isFinite(rating) ? rating : undefined,
        }
      : undefined,
  };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${gatewayUrl}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
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

export interface SystemStatus {
  catalog: {
    cleaning_status: string;
    source_fingerprint: string | null;
    cleaner_version: string | null;
    updated_at: string | null;
    error_code: string | null;
  };
  recommendations: {
    status: string;
    source_fingerprint: string | null;
    recommendations_available: boolean;
  };
  capabilities: {
    browse: boolean;
    reviews: boolean;
    recommendations: boolean;
  };
}

export interface AuditRun {
  run_id: string;
  source_fingerprint: string;
  cleaner_version: string;
  status: string;
  started_at: string;
  completed_at?: string;
  error_code?: string | null;
  metrics?: Record<string, number>;
  movies_examined?: number;
  reviews_examined?: number;
  llm_inferences?: number;
  llm_unresolved?: number;
  unresolved_ratings?: number;
}

export interface AuditDetail {
  entity_id: string;
  collection: string;
  category: string;
  field: string;
  before: unknown;
  after: unknown;
  reason: string;
  method: string;
  evidence: Record<string, unknown>;
  updated_at: string;
}

export function getMovies(query: MovieQuery = {}) {
  const params = new URLSearchParams();
  if (query.q?.trim()) params.set("q", query.q.trim());
  if (query.genre) params.set("genre", query.genre);
  params.set("page", String(query.page ?? 1));
  params.set("page_size", String(query.pageSize ?? 20));
  return request<PageResult<ApiMovie>>(`/api/movies?${params}`).then((result) => ({
    ...result,
    items: result.items.map(normalizeMovie),
  }));
}

export function getMovie(movieId: string) {
  return request<ApiMovie>(`/api/movies/${encodeURIComponent(movieId)}`).then(normalizeMovie);
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

export function getSystemStatus() {
  return request<SystemStatus>("/api/status");
}

export function getAuditRuns(limit = 20, offset = 0) {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  return request<{ items: AuditRun[]; total: number }>(`/api/audit/runs?${params}`);
}

export function getAuditRunDetails(runId: string, limit = 50, offset = 0) {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  return request<{ items: AuditDetail[]; total: number }>(
    `/api/audit/runs/${encodeURIComponent(runId)}/details?${params}`,
  );
}
