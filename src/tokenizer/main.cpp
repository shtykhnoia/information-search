#include "tokenizer.h"

#include <fstream>
#include <iostream>
#include <stdexcept>

int main(int argc, char* argv[]) {
    if (argc != 2) {
        std::cerr << "Usage: tokenizer <UTF-8 text file>\n";
        return 1;
    }

    std::ifstream input(argv[1], std::ios::binary);
    if (!input) {
        std::cerr << "Cannot open input file: " << argv[1] << '\n';
        return 1;
    }

    std::size_t line_number = 0;
    try {
        std::string line;
        while (std::getline(input, line)) {
            ++line_number;
            if (line_number == 1 && line.compare(0, 3, "\xEF\xBB\xBF") == 0) {
                line.erase(0, 3);
            }
            for (const auto& token : tokenize(line)) {
                std::cout << token << '\n';
            }
            if (!std::cout) {
                throw std::runtime_error("cannot write output");
            }
        }
        if (!input.eof()) {
            throw std::runtime_error("cannot read input file");
        }
        std::cout.flush();
        if (!std::cout) {
            throw std::runtime_error("cannot write output");
        }
    } catch (const std::exception& error) {
        std::cerr << argv[1] << ": line " << line_number << ": " << error.what() << '\n';
        return 1;
    }
    return 0;
}
