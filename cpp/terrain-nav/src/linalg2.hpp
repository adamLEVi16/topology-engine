#pragma once

#include <cmath>

// Just enough 2-D linear algebra for the per-particle bias filter. Everything
// here is 2x2, so the inverse is closed-form and there is no reason to pull in
// a matrix library.

struct Vec2 {
    double x = 0.0;
    double y = 0.0;

    Vec2& operator+=(const Vec2& o) { x += o.x; y += o.y; return *this; }
    Vec2& operator-=(const Vec2& o) { x -= o.x; y -= o.y; return *this; }
    Vec2& operator*=(double s)      { x *= s;   y *= s;   return *this; }
};

inline Vec2 operator+(Vec2 a, const Vec2& b) { return a += b; }
inline Vec2 operator-(Vec2 a, const Vec2& b) { return a -= b; }
inline Vec2 operator*(Vec2 a, double s)      { return a *= s; }
inline Vec2 operator*(double s, Vec2 a)      { return a *= s; }
inline double norm(const Vec2& a) { return std::sqrt(a.x * a.x + a.y * a.y); }

struct Mat2 {
    double m00 = 0.0, m01 = 0.0;
    double m10 = 0.0, m11 = 0.0;

    static Mat2 identity(double s = 1.0) { return Mat2{s, 0.0, 0.0, s}; }
};

inline Mat2 operator+(const Mat2& a, const Mat2& b) {
    return Mat2{a.m00 + b.m00, a.m01 + b.m01, a.m10 + b.m10, a.m11 + b.m11};
}

inline Mat2 operator-(const Mat2& a, const Mat2& b) {
    return Mat2{a.m00 - b.m00, a.m01 - b.m01, a.m10 - b.m10, a.m11 - b.m11};
}

inline Mat2 operator*(const Mat2& a, const Mat2& b) {
    return Mat2{a.m00 * b.m00 + a.m01 * b.m10, a.m00 * b.m01 + a.m01 * b.m11,
                a.m10 * b.m00 + a.m11 * b.m10, a.m10 * b.m01 + a.m11 * b.m11};
}

inline Mat2 operator*(const Mat2& a, double s) {
    return Mat2{a.m00 * s, a.m01 * s, a.m10 * s, a.m11 * s};
}

inline Vec2 operator*(const Mat2& a, const Vec2& v) {
    return Vec2{a.m00 * v.x + a.m01 * v.y, a.m10 * v.x + a.m11 * v.y};
}

inline Mat2 inverse(const Mat2& a) {
    const double det = a.m00 * a.m11 - a.m01 * a.m10;
    // Covariances here always carry additive process noise, so det > 0 in
    // practice; the guard only stops a pathological config from producing NaNs.
    const double inv_det = (std::fabs(det) > 1e-300) ? 1.0 / det : 0.0;
    return Mat2{ a.m11 * inv_det, -a.m01 * inv_det,
                -a.m10 * inv_det,  a.m00 * inv_det};
}

// Lower-triangular Cholesky factor, for drawing correlated Gaussian samples.
// Assumes a symmetric positive-definite input.
inline Mat2 cholesky(const Mat2& a) {
    const double l00 = std::sqrt(std::fmax(a.m00, 1e-300));
    const double l10 = a.m10 / l00;
    const double l11 = std::sqrt(std::fmax(a.m11 - l10 * l10, 0.0));
    return Mat2{l00, 0.0, l10, l11};
}
