// In the tests the results' code is there from the start, as the built page has it once
// fetched: a test draws the results at once, without waiting on a fetch.
import * as results from "../src/views/results";

export const resultsNow = () => results;
export const loadResults = () => Promise.resolve(results);
