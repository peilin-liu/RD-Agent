import request from './request';

export const url = typeof window !== 'undefined' ? `${window.location.origin}/` : '/';

async function qlibScriptRequest(path, config = {}) {
    const data = await request({ url: url + 'api/qlib-script/' + path, method: 'get', ...config });
    if (!data) throw new Error('训练服务暂时不可用');
    if (data && data.status >= 400) throw new Error(data.data?.error || 'Request failed');
    if (data && data.error) throw new Error(data.error);
    return data;
}

export const getTrainExperiments = () => qlibScriptRequest('experiments');
export const getTrainExperiment = (id) => qlibScriptRequest(`experiments/${encodeURIComponent(id)}`);
export const getTrainTasks = () => qlibScriptRequest('tasks');
export const previewTrainTask = (overrides) => qlibScriptRequest('tasks/preview', { method: 'post', data: { overrides } });
export const createTrainTask = (overrides) => qlibScriptRequest('tasks', { method: 'post', data: { overrides } });
export const stopTrainTask = (id) => qlibScriptRequest(`tasks/${encodeURIComponent(id)}/stop`, { method: 'post' });
export const getTrainHistory = (id, runId) => qlibScriptRequest(`experiments/${encodeURIComponent(id)}/history?` + new URLSearchParams({ run_id: runId }));
export const getTrainLog = (id, offset = 0, generation = '') => qlibScriptRequest(`experiments/${encodeURIComponent(id)}/logs?` + new URLSearchParams({ offset: String(offset), generation }));

export function uploadFile(data, config = {}) {
    return request({
        url: url + "upload",
        method: 'post',
        headers: {
            'Content-Type': 'multipart/form-data',
        },
        // onUploadProgress: progressEvent => {
        //     //   this.uploadPercentage = parseInt(Math.round((progressEvent.loaded / progressEvent.total) * 100));
        //     console.log(progressEvent)
        // },
        data: data,
        ...config
    })
}

export function trace(data) {
    return request({
        url: url + "trace",
        method: 'post',
        headers: {
            'Content-Type': 'application/json'
        },
        data: data
    })
}

export function getHistoryTraceIds() {
    return request({
        url: url + "traces",
        method: 'get'
    })
}

export function deleteTrace(traceId, { execute = false } = {}) {
    return request({
        url: url + "trace/delete",
        method: 'post',
        headers: {
            'Content-Type': 'application/json'
        },
        data: { trace_id: traceId, execute: execute }
    })
}

export async function fetchNextTraceIdAfterDelete(deletedTraceId) {
    // Refresh the trace list and pick a neighbour of the deleted one.
    // Prefer the trace that sorts immediately after the deleted id; fall back
    // to the previous one; if the list is empty return null.
    // NOTE: request.js response interceptor returns the raw `response.data`
    // (not the full axios response) on success, and returns `error.response`
    // (the full axios response object) on failure. Handle both shapes.
    try {
        const data = await getHistoryTraceIds();
        const ids = Array.isArray(data) ? data
            : (data && Array.isArray(data.data)) ? data.data
            : [];
        if (ids.length === 0) return null;
        const sorted = [...ids].sort();
        // Find where deletedTraceId would be; pick the first id that sorts
        // strictly after it, else the last id (the one before it).
        const after = sorted.find((id) => id > deletedTraceId);
        return after || sorted[sorted.length - 1];
    } catch (e) {
        return null;
    }
}

export function control(data) {
    return request({
        url: url + "control",
        method: 'post',
        headers: {
            'Content-Type': 'application/json'
        },
        data: data
    })
}

export function submitUserInteraction(data) {
    return request({
        url: url + "user_interaction/submit",
        method: 'post',
        headers: {
            'Content-Type': 'application/json'
        },
        data: data
    })
}

export function getStdoutDownloadUrl(traceId) {
    const query = new URLSearchParams({ id: traceId });
    return url + "stdout?" + query.toString();
}

export function listTraceArtifacts(traceId) {
    const query = new URLSearchParams({ trace_id: traceId });
    return request({
        url: url + "trace/artifacts?" + query.toString(),
        method: 'get'
    });
}

export function getTraceArtifactDownloadUrl(traceId, uuid, relPath) {
    const query = new URLSearchParams({ trace_id: traceId, uuid: uuid, path: relPath });
    return url + "trace/artifact/download?" + query.toString();
}

export function getRegions() {
    return request({
        url: url + "api/regions",
        method: 'get',
    })
}

export function getMarkets(region) {
    const query = new URLSearchParams({ region });
    return request({
        url: url + "api/markets?" + query.toString(),
        method: 'get',
    })
}

export function getBenchmarks(region) {
    const query = new URLSearchParams({ region });
    return request({
        url: url + "api/benchmarks?" + query.toString(),
        method: 'get',
    })
}

export function getInstruments(region, market) {
    const query = new URLSearchParams({ region, market: market || "all" });
    return request({
        url: url + "api/instruments/" + region + "?" + query.toString(),
        method: 'get',
    })
}

const pendingSnapshots = new Map();
export function getMarketSnapshot(region, market, date, adjustment, refresh = false) {
    const query = new URLSearchParams({ region, market: market || "all" });
    if (date) query.set("date", date);
    if (adjustment) {
        query.set("screening", "1");
        query.set("adjustment", adjustment);
    }
    const key = query.toString();
    if (pendingSnapshots.has(key)) return pendingSnapshots.get(key);
    if (refresh) query.set("refresh", "1");
    const pending = request({
        url: url + "api/market_snapshot/" + region + "?" + query.toString(),
        method: 'get',
    }).finally(() => pendingSnapshots.delete(key));
    pendingSnapshots.set(key, pending);
    return pending;
}

export function setRegion(region) {
    return request({
        url: url + "api/region",
        method: 'post',
        headers: {
            'Content-Type': 'application/json'
        },
        data: { region },
    })
}

export function getSymbols(region) {
    return request({
        url: url + `api/symbols/${region}`,
        method: 'get',
    })
}

export function getOHLCV(region, instruments, fields, start, end, adjustment, pitFields) {
    return request({
        url: url + `api/ohlcv/${region}`,
        method: 'post',
        headers: {
            'Content-Type': 'application/json'
        },
        data: { instruments, fields, start, end, adjustment, pit_fields: pitFields || [] },
    })
}

export function getCustomFactors() {
    // Returns the user-maintained custom factor map from ~/.rd-agent/factors.json
    // (name -> qlib expression). Missing file yields {}.
    return request({
        url: url + 'custom_factors',
        method: 'get',
    })
}

export function getScenarioInfo() {
    return request({
        url: url + "api/scenario_info",
        method: 'get',
    })
}

export function getDataRange() {
    return request({
        url: url + "api/data_range",
        method: 'get',
    })
}

export function reloadQlib(region) {
    return request({
        url: url + `api/qlib/reload/${region}`,
        method: 'post',
        headers: {
            'Content-Type': 'application/json'
        },
    })
}
