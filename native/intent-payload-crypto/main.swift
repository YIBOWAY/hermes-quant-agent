import CryptoKit
import Darwin
import Foundation
import Security

private let maxRequestBytes = 1_500_000
private let maxResponseBytes = 2_000_000
private let keychainService = "com.yiboway.hermes-quant-agent.intent-payload"

private enum HelperFailure: Error {
    case invalidRequest
    case requestTooLarge
    case responseTooLarge
    case keychainUnavailable
    case keyNotFound
    case keyCorrupt
    case cryptoFailed
    case ioFailed

    var code: String {
        switch self {
        case .invalidRequest: return "invalid_request"
        case .requestTooLarge: return "request_too_large"
        case .responseTooLarge: return "response_too_large"
        case .keychainUnavailable: return "keychain_unavailable"
        case .keyNotFound: return "key_not_found"
        case .keyCorrupt: return "key_corrupt"
        case .cryptoFailed: return "crypto_failed"
        case .ioFailed: return "io_failed"
        }
    }
}

private func parseDescriptors() throws -> (Int32, Int32) {
    let arguments = CommandLine.arguments
    guard arguments.count == 5,
          arguments[1] == "--request-fd",
          arguments[3] == "--response-fd",
          let request = Int32(arguments[2]),
          let response = Int32(arguments[4]),
          request >= 3,
          response >= 3,
          request != response else {
        throw HelperFailure.invalidRequest
    }
    return (request, response)
}

private func readBounded(fd: Int32) throws -> Data {
    let handle = FileHandle(fileDescriptor: fd, closeOnDealloc: false)
    var result = Data()
    while true {
        let chunk = handle.readData(ofLength: 65_536)
        if chunk.isEmpty { break }
        result.append(chunk)
        if result.count > maxRequestBytes {
            throw HelperFailure.requestTooLarge
        }
    }
    return result
}

private func writeBounded(_ object: [String: Any], fd: Int32) throws {
    let data: Data
    do {
        data = try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
    } catch {
        throw HelperFailure.ioFailed
    }
    if data.count > maxResponseBytes {
        throw HelperFailure.responseTooLarge
    }
    try data.withUnsafeBytes { rawBuffer in
        guard let base = rawBuffer.baseAddress else { return }
        var offset = 0
        while offset < data.count {
            let written = Darwin.write(fd, base.advanced(by: offset), data.count - offset)
            if written < 0 && errno == EINTR { continue }
            if written <= 0 { throw HelperFailure.ioFailed }
            offset += written
        }
    }
}

private func strictObject(_ data: Data) throws -> [String: Any] {
    guard let text = String(data: data, encoding: .utf8) else {
        throw HelperFailure.invalidRequest
    }
    let value: Any
    do {
        value = try JSONSerialization.jsonObject(with: data, options: [])
    } catch {
        throw HelperFailure.invalidRequest
    }
    guard let object = value as? [String: Any] else {
        throw HelperFailure.invalidRequest
    }
    // The private protocol is a flat object of ASCII field names and string
    // values. JSONSerialization otherwise accepts duplicate keys using a
    // last-value-wins rule, so count the raw key tokens and reject escaped,
    // duplicated, nested, or whitespace-variant key syntax before dispatch.
    // Field names are ASCII identifiers; digits are allowed (aad_b64, plaintext_b64, …).
    let expression = try NSRegularExpression(pattern: "\\\"([A-Za-z_][A-Za-z0-9_]*)\\\":")
    let range = NSRange(text.startIndex..<text.endIndex, in: text)
    let matches = expression.matches(in: text, range: range)
    var keys = Set<String>()
    for match in matches {
        guard let keyRange = Range(match.range(at: 1), in: text) else {
            throw HelperFailure.invalidRequest
        }
        let key = String(text[keyRange])
        if !keys.insert(key).inserted {
            throw HelperFailure.invalidRequest
        }
    }
    guard matches.count == object.count else {
        throw HelperFailure.invalidRequest
    }
    return object
}

private func exactKeys(_ object: [String: Any], _ expected: Set<String>) -> Bool {
    return Set(object.keys) == expected
}

private func boundedIdentifier(_ value: Any?) throws -> String {
    guard let identifier = value as? String,
          identifier.count >= 1,
          identifier.count <= 128,
          identifier.range(
              of: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
              options: .regularExpression
          ) != nil else {
        throw HelperFailure.invalidRequest
    }
    return identifier
}

private func base64(_ value: Any?, maximum: Int) throws -> Data {
    guard let text = value as? String,
          text.utf8.count <= ((maximum + 2) / 3) * 4 + 4,
          let decoded = Data(base64Encoded: text, options: []),
          decoded.count <= maximum else {
        throw HelperFailure.invalidRequest
    }
    return decoded
}

private func keyQuery(_ keyID: String) -> [CFString: Any] {
    // Use the traditional file-based keychain. Data Protection Keychain
    // (kSecUseDataProtectionKeychain) requires a keychain-access-groups
    // entitlement that adhoc/linker-signed CLI helpers do not carry
    // (OSStatus -34018 errSecMissingEntitlement). Traditional keychain
    // still honors kSecAttrAccessibleWhenUnlockedThisDeviceOnly below.
    return [
        kSecClass: kSecClassGenericPassword,
        kSecAttrService: keychainService,
        kSecAttrAccount: keyID,
        kSecAttrSynchronizable: kCFBooleanFalse as Any,
    ]
}

private func readKey(_ keyID: String) throws -> Data? {
    var query = keyQuery(keyID)
    query[kSecReturnData] = kCFBooleanTrue
    query[kSecMatchLimit] = kSecMatchLimitOne
    var result: CFTypeRef?
    let status = SecItemCopyMatching(query as CFDictionary, &result)
    if status == errSecItemNotFound { return nil }
    guard status == errSecSuccess else {
        throw HelperFailure.keychainUnavailable
    }
    guard let data = result as? Data, data.count == 32 else {
        throw HelperFailure.keyCorrupt
    }
    return data
}

private func loadKey(_ keyID: String, create: Bool) throws -> SymmetricKey {
    if let existing = try readKey(keyID) {
        return SymmetricKey(data: existing)
    }
    if !create { throw HelperFailure.keyNotFound }

    var bytes = Data(count: 32)
    let randomStatus = bytes.withUnsafeMutableBytes { rawBuffer -> Int32 in
        guard let baseAddress = rawBuffer.baseAddress else { return errSecAllocate }
        return SecRandomCopyBytes(kSecRandomDefault, 32, baseAddress)
    }
    guard randomStatus == errSecSuccess else {
        throw HelperFailure.keychainUnavailable
    }
    var add = keyQuery(keyID)
    add[kSecValueData] = bytes
    add[kSecAttrAccessible] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
    let addStatus = SecItemAdd(add as CFDictionary, nil)
    if addStatus == errSecDuplicateItem, let winner = try readKey(keyID) {
        return SymmetricKey(data: winner)
    }
    guard addStatus == errSecSuccess else {
        throw HelperFailure.keychainUnavailable
    }
    return SymmetricKey(data: bytes)
}

private func encrypt(_ request: [String: Any]) throws -> [String: Any] {
    guard exactKeys(request, [
        "schema_version", "operation", "key_id", "aad_b64", "plaintext_b64",
    ]),
          request["schema_version"] as? String == "1.0",
          request["operation"] as? String == "encrypt" else {
        throw HelperFailure.invalidRequest
    }
    let keyID = try boundedIdentifier(request["key_id"])
    let aad = try base64(request["aad_b64"], maximum: 750_000)
    let plaintext = try base64(request["plaintext_b64"], maximum: 750_000)
    let key = try loadKey(keyID, create: true)
    do {
        let box = try AES.GCM.seal(plaintext, using: key, authenticating: aad)
        return [
            "ok": true,
            "algorithm": "AES-256-GCM",
            "key_id": keyID,
            "nonce_b64": Data(box.nonce).base64EncodedString(),
            "ciphertext_b64": box.ciphertext.base64EncodedString(),
            "tag_b64": box.tag.base64EncodedString(),
        ]
    } catch {
        throw HelperFailure.cryptoFailed
    }
}

private func decrypt(_ request: [String: Any]) throws -> [String: Any] {
    guard exactKeys(request, [
        "schema_version", "operation", "key_id", "aad_b64", "nonce_b64",
        "ciphertext_b64", "tag_b64",
    ]),
          request["schema_version"] as? String == "1.0",
          request["operation"] as? String == "decrypt" else {
        throw HelperFailure.invalidRequest
    }
    let keyID = try boundedIdentifier(request["key_id"])
    let aad = try base64(request["aad_b64"], maximum: 750_000)
    let nonceData = try base64(request["nonce_b64"], maximum: 12)
    let ciphertext = try base64(request["ciphertext_b64"], maximum: 750_000)
    let tag = try base64(request["tag_b64"], maximum: 16)
    guard nonceData.count == 12, tag.count == 16 else {
        throw HelperFailure.invalidRequest
    }
    let key = try loadKey(keyID, create: false)
    do {
        let nonce = try AES.GCM.Nonce(data: nonceData)
        let box = try AES.GCM.SealedBox(nonce: nonce, ciphertext: ciphertext, tag: tag)
        let plaintext = try AES.GCM.open(box, using: key, authenticating: aad)
        return ["ok": true, "plaintext_b64": plaintext.base64EncodedString()]
    } catch {
        throw HelperFailure.cryptoFailed
    }
}

private func run(_ request: [String: Any]) throws -> [String: Any] {
    guard let operation = request["operation"] as? String else {
        throw HelperFailure.invalidRequest
    }
    switch operation {
    case "encrypt": return try encrypt(request)
    case "decrypt": return try decrypt(request)
    default: throw HelperFailure.invalidRequest
    }
}

do {
    let descriptors = try parseDescriptors()
    do {
        let request = try strictObject(readBounded(fd: descriptors.0))
        try writeBounded(try run(request), fd: descriptors.1)
    } catch let failure as HelperFailure {
        try writeBounded(["ok": false, "code": failure.code], fd: descriptors.1)
    } catch {
        try writeBounded(["ok": false, "code": "crypto_failed"], fd: descriptors.1)
    }
} catch {
    // No stdout/stderr protocol or diagnostics: a missing/invalid descriptor is
    // visible to the parent only as a non-zero, redacted helper failure.
    exit(64)
}
