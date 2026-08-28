export type PortfolioRealm = "a-share" | "etf";

export interface PortfolioMember {
  symbol: string;
  added_at?: string;
  note?: string;
}

export interface PortfolioRecord {
  id: string;
  name: string;
  realm: PortfolioRealm;
  members: PortfolioMember[];
  created_at?: string;
  updated_at?: string;
}

export interface PortfolioMemberSnapshot {
  symbol: string;
  name?: string | null;
  note?: string | null;
  price?: number | null;
  pct_change?: number | null;
  chg_5d?: number | null;
  chg_20d?: number | null;
}

export interface PortfolioSnapshot {
  portfolio_id: string;
  name: string;
  realm: PortfolioRealm;
  as_of: string;
  member_count: number;
  equal_weight_pct_1d?: number | null;
  equal_weight_chg_5d?: number | null;
  equal_weight_chg_20d?: number | null;
  members: PortfolioMemberSnapshot[];
  best_today?: PortfolioMemberSnapshot | null;
  worst_today?: PortfolioMemberSnapshot | null;
}

export interface TrackRecord {
  id: string;
  date: string;
  recorded_at: string;
  equal_weight_pct_1d?: number | null;
  equal_weight_chg_5d?: number | null;
  member_count: number;
  best_symbol?: string | null;
  best_name?: string | null;
  best_pct?: number | null;
  worst_symbol?: string | null;
  worst_name?: string | null;
  worst_pct?: number | null;
  note?: string | null;
  path_id?: string | null;
}

export interface PortfolioUpdateBody {
  name?: string;
  members?: PortfolioMember[];
}
