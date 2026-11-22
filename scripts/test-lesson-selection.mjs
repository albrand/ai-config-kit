import assert from 'node:assert/strict';
import { selectLessons } from './lib/lessons.mjs';

const lessons = [{name:'finish-the-job'}, {name:'meaningful-tests'}, {name:'unrelated'}];
assert.equal(selectLessons(lessons, []), lessons);
assert.deepEqual(selectLessons(lessons, ['--lesson','finish-the-job','--lesson','meaningful-tests']), lessons.slice(0,2));
assert.deepEqual(selectLessons(lessons, ['--lesson','finish-the-job','--lesson','finish-the-job']), lessons.slice(0,1));
assert.throws(() => selectLessons(lessons, ['--lesson']), /requires/);
assert.throws(() => selectLessons(lessons, ['--lesson','--force']), /requires/);
assert.throws(() => selectLessons(lessons, ['--lesson','unknown']), /Unknown/);
console.log('PASS: bounded lesson selection, unchanged default, and fail-before-write names.');
