#include "tokenizer.h"

#include <filesystem>
#include <fstream>
#include <functional>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <cstdlib>
#include <fcntl.h>
#include <sys/wait.h>
#include <unistd.h>

void require(bool condition, const std::string& message) {
    if (!condition) {
        throw std::runtime_error(message);
    }
}

std::string read_file(const std::filesystem::path& path) {
    std::ifstream file(path, std::ios::binary);
    return {std::istreambuf_iterator<char>(file), std::istreambuf_iterator<char>()};
}

struct Result {
    int status;
    std::string output;
    std::string error;
};

class Cli {
public:
    explicit Cli(const char* executable) : executable(executable) {
        std::string pattern = (std::filesystem::temp_directory_path() / "mai-ir-test-XXXXXX").string();
        const auto path = mkdtemp(pattern.data());
        require(path != nullptr, "cannot create temporary directory");
        directory = path;
    }

    ~Cli() {
        std::error_code error;
        std::filesystem::remove_all(directory, error);
    }

    Result run(const std::vector<std::string>& arguments) {
        std::vector<char*> argv = {executable.data()};
        for (const auto& argument : arguments) {
            argv.push_back(const_cast<char*>(argument.c_str()));
        }
        argv.push_back(nullptr);
        const auto pid = fork();
        require(pid >= 0, "cannot start tokenizer");
        if (pid == 0) {
            alarm(30);
            const auto out = open((directory / "stdout").c_str(), O_WRONLY | O_CREAT | O_TRUNC, 0600);
            const auto err = open((directory / "stderr").c_str(), O_WRONLY | O_CREAT | O_TRUNC, 0600);
            if (out < 0 || err < 0 || dup2(out, STDOUT_FILENO) < 0 || dup2(err, STDERR_FILENO) < 0) {
                _exit(127);
            }
            close(out);
            close(err);
            execv(executable.c_str(), argv.data());
            _exit(127);
        }
        int status = 0;
        require(waitpid(pid, &status, 0) == pid, "cannot wait for tokenizer");
        require(WIFEXITED(status), "tokenizer terminated abnormally");
        return {WEXITSTATUS(status), read_file(directory / "stdout"), read_file(directory / "stderr")};
    }

    Result text(const std::string& content) {
        const auto path = directory / "input.txt";
        {
            std::ofstream file(path, std::ios::binary);
            file.write(content.data(), content.size());
            require(static_cast<bool>(file), "cannot write input fixture");
        }
        return run({path.string()});
    }

    std::filesystem::path directory;

private:
    std::string executable;
};

int main(int argc, char* argv[]) {
    if (argc != 2) {
        std::cerr << "Usage: tokenizer_tests <tokenizer executable>\n";
        return 1;
    }
    Cli cli(argv[1]);
    int passed = 0;
    int failed = 0;
    const auto test = [&](const std::string& name, const std::function<void()>& body) {
        try {
            body();
            ++passed;
            std::cout << "PASS " << name << std::endl;
        } catch (const std::exception& error) {
            ++failed;
            std::cerr << "FAIL " << name << ": " << error.what() << std::endl;
        }
    };
    const auto tokens = [&](const std::string& name, const std::string& input,
                            const std::vector<std::string>& expected) {
        test(name, [&] {
            require(tokenize(input) == expected, "unexpected tokens from function");
            const auto result = cli.text(input);
            std::string output;
            for (const auto& token : expected) {
                output += token + '\n';
            }
            require(result.status == 0 && result.error.empty(), "CLI failed: " + result.error);
            require(result.output == output, "unexpected CLI output");
        });
    };

    tokens("russian and english case", "МАТРИЦА The Matrix Яя Аа Zz", {"матрица", "the", "matrix", "яя", "аа", "zz"});
    tokens("yo remains distinct", "Ёж ёж ЕЖ", {"ёж", "ёж", "еж"});
    tokens("numbers and mixed words", "Т-34 A320 3D 007 12.5", {"т", "34", "a320", "3d", "007", "12", "5"});
    tokens("punctuation", "«Человек-паук» — Spider–Man; don't/stop_!", {"человек", "паук", "spider", "man", "don", "t", "stop"});
    tokens("repetitions and stop words", "И и в THE the", {"и", "и", "в", "the", "the"});
    tokens("line endings", "один\r\nдва\n\nтри\tчетыре\rпять", {"один", "два", "три", "четыре", "пять"});
    tokens("empty", "", {});
    tokens("delimiters only", " \n\t!?—", {});
    tokens("BOM", "\xEF\xBB\xBFПервый\nвторой", {"первый", "второй"});
    tokens("unsupported characters", "кот😀пёс café 中文 αβ", {"кот", "пёс", "caf"});
    tokens("embedded zero byte", std::string("a\0b", 3), {"a", "b"});
    tokens("valid UTF-8 boundaries", "a\xC2\x80\xDF\xBF\xE0\xA0\x80\xED\x9F\xBF\xEE\x80\x80\xEF\xBF\xBF\xF0\x90\x80\x80\xF4\x8F\xBF\xBF z", {"a", "z"});

    test("invalid UTF-8", [&] {
        for (const auto& input : {"\x80", "\xC0\xAF", "\xC2", "\xD0x", "\xE0\x80\x80",
                                  "\xED\xA0\x80", "\xF0\x80\x80\x80", "\xF4\x90\x80\x80", "\xFF"}) {
            bool rejected = false;
            try {
                tokenize(input);
            } catch (const std::runtime_error&) {
                rejected = true;
            }
            require(rejected, "function accepted invalid UTF-8");
            const auto result = cli.text(input);
            require(result.status != 0, "CLI accepted invalid UTF-8");
            require(result.error.find("invalid UTF-8") != std::string::npos, "missing UTF-8 error");
        }
    });
    test("error after valid line", [&] {
        const auto result = cli.text("first\n\xFF");
        require(result.status != 0 && result.output == "first\n", "incorrect partial output");
        require(result.error.find("line 2") != std::string::npos, "incorrect error location");
    });
    test("missing file and arguments", [&] {
        for (const auto& arguments : std::vector<std::vector<std::string>>{
                 {}, {(cli.directory / "missing.txt").string()}, {"one", "two"}}) {
            const auto result = cli.run(arguments);
            require(result.status != 0 && !result.error.empty() && result.output.empty(), "incorrect error handling");
        }
    });
    test("large file", [&] {
        std::string input;
        std::string expected;
        for (int i = 0; i < 100000; ++i) {
            input += "Матрица 1999 Neo\n";
            expected += "матрица\n1999\nneo\n";
        }
        const auto result = cli.text(input);
        require(result.status == 0 && result.error.empty(), "large file failed");
        require(result.output == expected, "large file output mismatch");
    });
    std::cout << passed << " passed, " << failed << " failed\n";
    return failed == 0 ? 0 : 1;
}
