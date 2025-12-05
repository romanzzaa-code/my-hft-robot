#include <pybind11/pybind11.h>

namespace py = pybind11;

PYBIND11_MODULE(hft_core, m) {
    m.doc() = "HFT Core Module implemented in C++";
}