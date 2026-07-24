import request from './request';

export const url = typeof window !== 'undefined' ? `${window.location.origin}/` : '/';

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

export function getInstruments(region, market) {
    const query = new URLSearchParams({ region, market: market || "all" });
    return request({
        url: url + "api/instruments/" + region + "?" + query.toString(),
        method: 'get',
    })
}

export function getMarketSnapshot(region, market, date) {
    const query = new URLSearchParams({ region, market: market || "all" });
    if (date) query.set("date", date);
    return request({
        url: url + "api/market_snapshot/" + region + "?" + query.toString(),
        method: 'get',
    })
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

export function getOHLCV(region, instruments, fields, start, end, adjust, pitFields) {
    return request({
        url: url + `api/ohlcv/${region}`,
        method: 'post',
        headers: {
            'Content-Type': 'application/json'
        },
        data: { instruments, fields, start, end, adjust, pit_fields: pitFields || [] },
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
