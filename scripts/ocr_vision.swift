import Vision
import AppKit
import Foundation

let args = CommandLine.arguments
guard args.count > 1,
      let image = NSImage(contentsOfFile: args[1]),
      let cg = image.cgImage(forProposedRect: nil, context: nil, hints: nil)
else {
    FileHandle.standardError.write("ERROR: cannot load image\n".data(using: .utf8)!)
    exit(1)
}

let request = VNRecognizeTextRequest { req, _ in
    let observations = req.results as? [VNRecognizedTextObservation] ?? []
    let text = observations
        .compactMap { $0.topCandidates(1).first?.string }
        .joined(separator: "\n")
    print(text)
}
request.recognitionLevel = .accurate

let handler = VNImageRequestHandler(cgImage: cg, options: [:])
do {
    try handler.perform([request])
} catch {
    FileHandle.standardError.write("ERROR: \(error)\n".data(using: .utf8)!)
    exit(1)
}
