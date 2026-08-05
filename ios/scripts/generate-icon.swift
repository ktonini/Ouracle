// Generates the Ouracle app icon (1024x1024 PNG) with CoreGraphics.
// Run: swift ios/scripts/generate-icon.swift <output.png>
//
// Design: deep night-sky gradient with a three-arc ring — the app's
// sleep/readiness/activity score rings fused into an "O" for Ouracle,
// echoing the physical ring itself.

import AppKit
import CoreGraphics

let size = 1024
let out = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "icon.png"

let colorSpace = CGColorSpace(name: CGColorSpace.sRGB)!
let ctx = CGContext(
    data: nil, width: size, height: size, bitsPerComponent: 8, bytesPerRow: 0,
    space: colorSpace, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
)!

let s = CGFloat(size)
let center = CGPoint(x: s / 2, y: s / 2)

// --- Background: radial night gradient, slightly off-center like moonlight.
let bgColors = [
    CGColor(red: 0.16, green: 0.17, blue: 0.30, alpha: 1),  // indigo glow
    CGColor(red: 0.07, green: 0.07, blue: 0.14, alpha: 1),  // midnight
    CGColor(red: 0.03, green: 0.03, blue: 0.07, alpha: 1),  // near-black edge
] as CFArray
let bgGradient = CGGradient(colorsSpace: colorSpace, colors: bgColors, locations: [0, 0.55, 1])!
ctx.drawRadialGradient(
    bgGradient,
    startCenter: CGPoint(x: s * 0.38, y: s * 0.66), startRadius: 0,
    endCenter: center, endRadius: s * 0.85,
    options: [.drawsAfterEndLocation]
)

// --- Faint stars.
srand48(7)
for _ in 0..<70 {
    let x = CGFloat(drand48()) * s
    let y = CGFloat(drand48()) * s
    let r = CGFloat(drand48()) * 2.2 + 0.6
    let d = hypot(x - center.x, y - center.y)
    if d < s * 0.40 { continue }  // keep the ring area clean
    ctx.setFillColor(CGColor(gray: 1, alpha: CGFloat(drand48()) * 0.35 + 0.08))
    ctx.fillEllipse(in: CGRect(x: x - r, y: y - r, width: r * 2, height: r * 2))
}

// --- The ring: three arcs with small gaps, score-band colors.
let radius = s * 0.30
let lineWidth = s * 0.085
let gap = CGFloat.pi * 0.045
let arcs: [(CGColor, CGFloat, CGFloat)] = [
    // (color, startAngle, endAngle) — measured counterclockwise from +x axis
    (CGColor(red: 0.30, green: 0.80, blue: 0.50, alpha: 1), .pi / 2 + gap, .pi * 7 / 6 - gap),      // green (activity)
    (CGColor(red: 0.35, green: 0.55, blue: 0.95, alpha: 1), .pi * 7 / 6 + gap, .pi * 11 / 6 - gap), // blue (sleep)
    (CGColor(red: 0.95, green: 0.65, blue: 0.30, alpha: 1), .pi * 11 / 6 + gap, .pi * 5 / 2 - gap), // amber (readiness)
]

// Soft glow pass under the arcs.
for (color, start, end) in arcs {
    ctx.saveGState()
    ctx.setShadow(offset: .zero, blur: s * 0.05, color: color.copy(alpha: 0.85))
    ctx.setStrokeColor(color)
    ctx.setLineWidth(lineWidth)
    ctx.setLineCap(.round)
    ctx.addArc(
        center: center, radius: radius,
        startAngle: start, endAngle: end, clockwise: false
    )
    ctx.strokePath()
    ctx.restoreGState()
}

// --- Small moon dot in the center gap of the ring.
let moonRadius = s * 0.085
ctx.setFillColor(CGColor(red: 0.92, green: 0.93, blue: 0.98, alpha: 0.95))
ctx.fillEllipse(in: CGRect(
    x: center.x - moonRadius, y: center.y - moonRadius,
    width: moonRadius * 2, height: moonRadius * 2
))
// Crescent shadow bite.
ctx.setFillColor(CGColor(red: 0.07, green: 0.07, blue: 0.14, alpha: 1))
ctx.fillEllipse(in: CGRect(
    x: center.x - moonRadius * 0.55, y: center.y - moonRadius * 0.75,
    width: moonRadius * 2, height: moonRadius * 2
))

// --- Write PNG.
let image = ctx.makeImage()!
let rep = NSBitmapImageRep(cgImage: image)
let png = rep.representation(using: .png, properties: [:])!
try! png.write(to: URL(fileURLWithPath: out))
print("wrote \(out)")
