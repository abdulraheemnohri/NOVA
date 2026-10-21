import {describe,expect,it} from "vitest";
import {formatAllowedPaths,parseAllowedPaths} from "../src/lib/apiAllowlist";

describe("API allowlist editor serialization",()=>{
  it("formats paths as real newline-separated lines",()=>{
    expect(formatAllowedPaths(["/v1/health","/v1/items"])).toBe("/v1/health\n/v1/items");
  });
  it("parses LF input and trims blank lines",()=>{
    expect(parseAllowedPaths(" /v1/health \n\n/v1/items\n ")).toEqual(["/v1/health","/v1/items"]);
  });
  it("parses Windows CRLF input",()=>{
    expect(parseAllowedPaths("/v1/health\r\n/v1/items\r\n")).toEqual(["/v1/health","/v1/items"]);
  });
  it("returns an empty list for blank input",()=>{
    expect(parseAllowedPaths(" \n\r\n ")).toEqual([]);
  });
});
