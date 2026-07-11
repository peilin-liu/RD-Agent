// Type declarations for API utilities
declare module '@/utils/api' {
  export function uploadFile(data: any, config?: any): Promise<any>;
  export function trace(data: any): Promise<any>;
  export function getHistoryTraceIds(): Promise<any>;
  export function control(data: any): Promise<any>;
  export function submitUserInteraction(data: any): Promise<any>;
  export function getStdoutDownloadUrl(traceId: string): string;
  export function getRegions(): Promise<{ regions: string[]; default_region: string }>;
  export function setRegion(region: string): Promise<any>;
  export function getSymbols(region: string): Promise<Array<{ symbol: string; name: string; listing_date?: string }>>;
  export function getOHLCV(
    region: string,
    instruments: string[],
    fields: string[],
    start: string,
    end: string,
    adjust?: boolean
  ): Promise<{ columns: string[]; data: any[][] }>;
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
}
