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

export function getOHLCV(region, instruments, fields, start, end, adjust) {
    return request({
        url: url + `api/ohlcv/${region}`,
        method: 'post',
        headers: {
            'Content-Type': 'application/json'
        },
        data: { instruments, fields, start, end, adjust },
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
