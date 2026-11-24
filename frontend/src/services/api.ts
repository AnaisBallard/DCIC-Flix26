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
