#include "tokenizer.h"

#include <cstdint>
#include <stdexcept>

namespace {

constexpr std::uint32_t ascii_limit = 128;
constexpr std::uint32_t two_byte_minimum = 128;
constexpr std::uint32_t three_byte_minimum = 2048;
constexpr std::uint32_t four_byte_minimum = 65536;
constexpr std::uint32_t unicode_maximum = 0x10FFFF;
constexpr std::uint32_t surrogate_first = 0xD800;
constexpr std::uint32_t surrogate_last = 0xDFFF;
constexpr unsigned char continuation_prefix = 0b10000000;
constexpr unsigned char continuation_prefix_mask = 0b11000000;
constexpr unsigned char continuation_data_mask = 0b00111111;
constexpr int continuation_data_bits = 6;

std::uint32_t read_codepoint(std::string_view text, std::size_t& offset) {
    const auto start = offset;
    const auto first = static_cast<unsigned char>(text[offset++]);
    if (first < ascii_limit) {
        return first;
    }

    int continuation = 0;
    std::uint32_t codepoint = 0;
    std::uint32_t minimum = 0;
    if (first >= 0b11000010 && first <= 0b11011111) {
        continuation = 1;
        codepoint = first & 0b00011111;
        minimum = two_byte_minimum;
    } else if (first >= 0b11100000 && first <= 0b11101111) {
        continuation = 2;
        codepoint = first & 0b00001111;
        minimum = three_byte_minimum;
    } else if (first >= 0b11110000 && first <= 0b11110100) {
        continuation = 3;
        codepoint = first & 0b00000111;
        minimum = four_byte_minimum;
    }

    const auto invalid = [start]() {
        return std::runtime_error("invalid UTF-8 at byte " + std::to_string(start + 1));
    };
    if (continuation == 0) {
        throw invalid();
    }
    for (int i = 0; i < continuation; ++i) {
        if (offset == text.size()) {
            throw invalid();
        }
        const auto byte = static_cast<unsigned char>(text[offset++]);
        if ((byte & continuation_prefix_mask) != continuation_prefix) {
            throw invalid();
        }
        codepoint = (codepoint << continuation_data_bits) | (byte & continuation_data_mask);
    }
    if (codepoint < minimum || codepoint > unicode_maximum ||
        (codepoint >= surrogate_first && codepoint <= surrogate_last)) {
        throw invalid();
    }
    return codepoint;
}

std::uint32_t lowercase(std::uint32_t ch) {
    if (ch >= U'A' && ch <= U'Z') {
        return ch + (U'a' - U'A');
    }
    if (ch >= U'А' && ch <= U'Я') {
        return ch + (U'а' - U'А');
    }
    return ch == U'Ё' ? U'ё' : ch;
}

bool is_token_character(std::uint32_t ch) {
    return (ch >= 'a' && ch <= 'z') || (ch >= '0' && ch <= '9') ||
           (ch >= U'а' && ch <= U'я') || ch == U'ё';
}

void append_token_character(std::string& token, std::uint32_t ch) {
    if (ch < ascii_limit) {
        token += static_cast<char>(ch);
    } else {
        token += static_cast<char>(0b11000000 | (ch >> continuation_data_bits));
        token += static_cast<char>(continuation_prefix | (ch & continuation_data_mask));
    }
}

}

std::vector<std::string> tokenize(std::string_view text) {
    std::vector<std::string> tokens;
    std::string token;
    std::size_t offset = 0;
    while (offset < text.size()) {
        const auto ch = lowercase(read_codepoint(text, offset));
        if (is_token_character(ch)) {
            append_token_character(token, ch);
        } else if (!token.empty()) {
            tokens.push_back(token);
            token.clear();
        }
    }
    if (!token.empty()) {
        tokens.push_back(token);
    }
    return tokens;
}
