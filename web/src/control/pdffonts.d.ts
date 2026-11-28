// The mathematics' faces, written into the PDF code as data: a PDF carries the faces it sets
// its Greek in, and the build keeps no other copy of them.
declare module "*.ttf?inline" {
  const data: string;
  export default data;
}

// The page's own typeface, by the address the build gave it.
declare module "*.woff2?url" {
  const url: string;
  export default url;
}
