import assert from 'node:assert/strict';
import test, { after } from 'node:test';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createRequire } from 'node:module';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
const require = createRequire(import.meta.url);
const output = mkdtempSync(join(tmpdir(), 'rd-screener-'));
after(() => rmSync(output, { recursive: true, force: true }));
execFileSync(process.execPath, [require.resolve('typescript/bin/tsc'),
  fileURLToPath(new URL('../src/utils/stockScreener.ts', import.meta.url)),
  '--outDir', output, '--module', 'commonjs', '--target', 'es2020', '--skipLibCheck']);
const { emptyScreen, copyScreen, matchesScreen, screenError, indicatorFieldsFor, chipFieldsFor, screeningRuleLabel, screenCount } = require(join(output, 'stockScreener.js'));
const range = (field, min = '', max = '') => ({ field, min, max });

test('industries match any selected industry; numeric conditions must all match', () => {
  const screen = { industries: ['银行', '食品'], maRules: [range('ma10_slope', '-1', '0'), range('ma500_slope', '0')],
    rules: [range('pe', '10', '20'), range('winner_rate', '50', '80')] };
  const metrics = { ma10_slope: -1, ma500_slope: 0, pe: 20, winner_rate: 50 };
  for (const industry of screen.industries) assert.equal(matchesScreen(industry, metrics, screen), true);
  assert.equal(matchesScreen('医药', metrics, screen), false);
  assert.equal(matchesScreen(undefined, metrics, screen), false);
  for (const field of Object.keys(metrics)) {
    assert.equal(matchesScreen('银行', { ...metrics, [field]: null }, screen), false);
    assert.equal(matchesScreen('银行', { ...metrics, [field]: Infinity }, screen), false);
  }
  assert.equal(matchesScreen('银行', { ...metrics, pe: 21 }, screen), false);
  assert.equal(matchesScreen(undefined, undefined, emptyScreen()), true);
});

test('dynamic indicators and all chart MA periods accept inclusive one-sided ranges', () => {
  const fields = indicatorFieldsFor(['custom_indicator', 'winner_rate', 'custom_indicator']);
  assert.equal(fields.length, 1);
  for (const period of [5, 10, 20, 30, 60, 250, 500]) {
    const screen = { ...emptyScreen(), maRules: [range(`ma${period}_slope`, '', '0')], rules: [range('custom_indicator', '-2.5')] };
    assert.equal(screenError(screen, fields), '');
    assert.equal(matchesScreen('', { [`ma${period}_slope`]: 0, custom_indicator: -2.5 }, screen), true);
  }
});

test('invalid bounds are rejected in both rule categories; drafts stay isolated', () => {
  for (const key of ['maRules', 'rules']) {
    const field = key === 'maRules' ? 'ma250_slope' : 'pe';
    for (const [min, max] of [['', ''], ['NaN', ''], ['', 'Infinity'], ['2', '1']]) {
      assert.ok(screenError({ ...emptyScreen(), [key]: [range(field, min, max)] }));
    }
  }
  const original = { industries: ['银行'], maRules: [range('ma5_slope', '0')], rules: [range('pe', '', '20')] };
  const draft = copyScreen(original);
  draft.industries.push('食品'); draft.maRules[0].min = '-1'; draft.rules[0].max = '30';
  assert.deepEqual(original, { industries: ['银行'], maRules: [range('ma5_slope', '0')], rules: [range('pe', '', '20')] });
});


test('chip rules combine with other categories, preserve units, and handle missing values', () => {
  const screen = { ...emptyScreen(), industries: ['食品'], maRules: [range('ma5_slope', '0')],
    rules: [range('pe', '10', '20')], chipRules: [range('chip_band_70_position', '100'), range('winner_rate_change_5d', '-10', '5')] };
  const metrics = { ma5_slope: 0.1, pe: 15, chip_band_70_position: 150, winner_rate_change_5d: -5 };
  assert.equal(screenError(screen), '');
  assert.equal(matchesScreen('食品', metrics, screen), true);
  assert.equal(matchesScreen('食品', { ...metrics, chip_band_70_position: 99 }, screen), false);
  assert.equal(matchesScreen('食品', { ...metrics, winner_rate_change_5d: null }, screen), false);
  assert.equal(screenCount(screen), 5);
  assert.match(screeningRuleLabel(screen.chipRules[1]), /个百分点/);
  assert.match(screeningRuleLabel(screen.chipRules[0]), /100%/);
  const draft = copyScreen(screen); draft.chipRules[0].min = '200';
  assert.equal(screen.chipRules[0].min, '100');
  assert.equal(chipFieldsFor(['winner_rate', 'unknown']).length, 1);
  assert.ok(screenError(screen, undefined, chipFieldsFor(['winner_rate'])));
  for (const [min, max] of [['', ''], ['NaN', ''], ['', 'Infinity'], ['2', '1']]) {
    assert.ok(screenError({ ...emptyScreen(), chipRules: [range('winner_rate', min, max)] }));
  }
});
