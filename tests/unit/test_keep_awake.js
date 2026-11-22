// SPDX-License-Identifier: GPL-3.0-or-later
// Run with: gjs -m tests/unit/test_keep_awake.js
import System from 'system';

import {minutesLeft, nextOccurrence, plan, remaining, stepMinutes}
    from '../../extensions/keep-awake/timing.js';

let failures = 0;
function check(name, condition) {
    if (!condition) {
        failures++;
        printerr(`FAIL: ${name}`);
    } else {
        print(`ok: ${name}`);
    }
}

const now = new Date(2026, 10, 21, 16, 30, 0);
const monotonic = 1e12;
const base = {now, monotonic, customMinutes: 90, untilMinutes: 17 * 60};

check('indefinite has no end', remaining(plan('indefinite', base), base) === null);
const fifteen = plan('15', base);
check('15 minutes', remaining(fifteen, base) === 900);
check('custom duration', remaining(plan('custom', base), base) === 90 * 60);
check('later today', nextOccurrence(now, 17 * 60).getDate() === 21 &&
    remaining(plan('until', base), base) === 30 * 60);
check('earlier time means tomorrow', nextOccurrence(now, 9 * 60).getDate() === 22);
check('the same minute means tomorrow', nextOccurrence(new Date(2026, 10, 21, 17, 0), 17 * 60).getDate() === 22);

// The wall clock jumps an hour forward: a duration is not shortened...
const jumped = {now: new Date(now.getTime() + 3600e3), monotonic: monotonic + 60e6};
check('duration ignores clock changes', remaining(fifteen, jumped) === 840);
// ...but "until 17:00" is over.
check('until follows the clock', remaining(plan('until', base), jumped) === 0);
check('duration ends', remaining(fifteen, {now, monotonic: monotonic + 901e6}) === 0);

// Daylight saving time: on the night of the change "until 3:00" is the next
// local 3:00, whatever the length of the night.
const evening = new Date(2026, 9, 24, 23, 0);
const three = nextOccurrence(evening, 3 * 60);
check('until across a daylight saving change', three.getHours() === 3 && three.getDate() === 25);

check('minutes rounded up', minutesLeft(61) === 2 && minutesLeft(60) === 1);
check('steps are clamped', stepMinutes(10, -15, 5, 720) === 5 && stepMinutes(715, 15, 5, 720) === 720);
check('time wraps around midnight', stepMinutes(1430, 15, 0, 1439, true) === 5 &&
    stepMinutes(5, -15, 0, 1439, true) === 1430);

if (failures) {
    printerr(`${failures} failed`);
    System.exit(1);
}
