export interface Movie {
  _id: string;
  title: string;
  year?: number | string;
  genres?: string[];
  poster?: string;
  plot?: string;
  fullplot?: string;
  runtime?: number;
  rated?: string;
  cast?: string[];
  directors?: string[];
  imdb?: { rating?: number; votes?: number | string };
  metacritic?: number;
}

export interface PageResult<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface Review {
  _id?: string;
  movie_id: string;
  user_id: string;
  rating: number;
  comment: string;
  date?: string;
}

export interface ReviewReceipt {
  status: string;
  event_id: string;
}
