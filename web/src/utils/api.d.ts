// Type declarations for API utilities
declare module '@/utils/api' {
  export function uploadFile(data: any, config?: any): Promise<any>;
  export function trace(data: any): Promise<any>;
  export function getHistoryTraceIds(): Promise<any>;
  export function control(data: any): Promise<any>;
  export function submitUserInteraction(data: any): Promise<any>;
  export function getStdoutDownloadUrl(traceId: string): string;
  export function getRegions(): Promise<{ regions: string[]; default_region: string }>;
  export function getMarkets(region: string): Promise<{ region: string; markets: string[] }>;
  export function getInstruments(region: string, market?: string): Promise<{
    region: string;
    market: string;
    instruments: Array<{ symbol: string; name: string; listing_date: string; industry_code: string; industry_name: string }>;
    error?: string;
  }>;
  export function getMarketSnapshot(region: string, market?: string, date?: string): Promise<{
    region: string;
    market: string;
    date: string;
    symbols_count: number;
    data: Array<{
      symbol: string;
      name: string;
      industry_code: string;
      industry_name: string;
      open: number | null;
      close: number | null;
      high: number | null;
      low: number | null;
      pct_chg: number | null;
      turnover: number | null;
      volume: number | null;
      amount: number | null;
      PE: number | null;
      PB: number | null;
      DV_RATIO: number | null;
      DV_TTM: number | null;
    }>;
    error?: string;
  }>;
  export function setRegion(region: string): Promise<any>;
  export function getSymbols(region: string): Promise<Array<{ symbol: string; name: string; listing_date?: string }>>;
  export function getOHLCV(
    region: string,
    instruments: string[],
    fields: string[],
    start: string,
    end: string,
    adjust?: boolean,
    pitFields?: string[]
  ): Promise<{
    columns: string[];
    data: any[][];
    ohlcv_fields?: string[];
    tech_fields?: string[];
    pit_factors?: string[];
    pit_overlay_fields?: string[];
    error?: string;
  }>;
  export interface ScenarioDataSplit {
    train_start: string;
    train_end: string;
    valid_start: string;
    valid_end: string;
    test_start: string;
    test_end: string | null;
  }
  export function getScenarioInfo(): Promise<{ factor: ScenarioDataSplit; model: ScenarioDataSplit; quant: ScenarioDataSplit }>;
  export function getDataRange(): Promise<{ regions: Record<string, { start: string; end: string; error?: string }> }>;
  export function reloadQlib(region: string): Promise<{
    status: string;
    region: string;
    data_range: { start: string; end: string };
    symbols_count: number;
    error?: string;
    trace?: string;
  }>;
}
