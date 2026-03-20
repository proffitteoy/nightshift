export interface AIUsageStats {
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
}

export interface LogEntry {
  id: string;
  timestamp: Date;
  type: 'info' | 'success' | 'error' | 'ai';
  message: string;
  details?: {
    request?: any;
    response?: any;
    filteredFiles?: string[];
    data?: any;
    usage?: AIUsageStats;
  };
}
