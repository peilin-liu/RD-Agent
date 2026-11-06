import assert from 'node:assert/strict';
import test from 'node:test';
import { metricSeriesHasData } from '../src/utils/metricSeries.js';
import { qlibDisplayMetrics } from '../src/utils/qlibMetrics.js';

test('script experiment metrics reach charts in ResultPage series format', () => {
  const metrics = qlibDisplayMetrics({
    'Rank ICIR': 0.6580134497511193,
    '1day.excess_return_with_cost.annualized_return': 0.32116814387082737,
    '1day.excess_return_without_cost.annualized_return': 0.35118989143295665,
  });
  const series = value => [{ name: 'rolling_example', value, desc: 'rolling_example' }];
  assert.equal(metricSeriesHasData(series(metrics['Rank ICIR'])), true);
  assert.equal(metricSeriesHasData(series(metrics['年化超额收益'])), true);
  assert.equal(metricSeriesHasData(series(metrics['最大回撤'])), false);
});

test('native rounds keep zero, negative and partially missing values visible', () => {
  assert.equal(metricSeriesHasData([{ name: 'Round1', value: null }, { name: 'Round2', value: 0 }]), true);
  assert.equal(metricSeriesHasData([{ name: 'Round1', value: -0.15 }]), true);
  assert.equal(metricSeriesHasData([{ name: 'Round1', value: { 含成本: null, 不含成本: 0 } }]), true);
});

test('empty and nonfinite metric series remain unavailable', () => {
  for (const series of [null, undefined, [], {}, [null], [{ value: null }], [{ value: NaN }],
    [{ value: Infinity }], [{ value: { 含成本: null, 不含成本: NaN } }]]) {
    assert.equal(metricSeriesHasData(series), false);
  }
});
