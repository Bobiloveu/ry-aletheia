#include "video_io.hpp"

#include <fcntl.h>
#include <poll.h>
#include <sys/prctl.h>
#include <sys/wait.h>
#include <unistd.h>

#include <atomic>
#include <cerrno>
#include <chrono>
#include <csignal>
#include <iostream>
#include <stdexcept>
#include <thread>
#include <vector>

#define REQUIRE(expr)                             \
  do {                                            \
    if (!(expr)) throw std::runtime_error(#expr); \
  } while (false)
int parent_death_notification = -1;
void parent_died(int) {
  const char event = 'T';
  if (write(parent_death_notification, &event, 1) != 1) _exit(127);
  _exit(0);
}

void parent_death_reaps_native_child() {
  REQUIRE(prctl(PR_SET_CHILD_SUBREAPER, 1) == 0);
  int notification[2], control[2];
  REQUIRE(pipe(notification) == 0 && pipe(control) == 0);
  const pid_t middle = fork();
  REQUIRE(middle >= 0);
  if (middle == 0) {
    close(notification[0]);
    close(control[1]);
    const pid_t expected_parent = getpid();
    const pid_t worker = fork();
    if (worker < 0) _exit(127);
    if (worker == 0) {
      close(control[0]);
      parent_death_notification = notification[1];
      signal(SIGTERM, parent_died);
      if (!aletheia::video::bind_parent_lifetime(expected_parent)) _exit(126);
      const char ready = 'R';
      if (write(notification[1], &ready, 1) != 1) _exit(125);
      for (;;) pause();
    }
    close(notification[1]);
    char exit_command;
    if (read(control[0], &exit_command, 1) != 1) _exit(124);
    _exit(0);
  }
  close(notification[1]);
  close(control[0]);
  pollfd event{notification[0], POLLIN, 0};
  char byte;
  REQUIRE(poll(&event, 1, 1000) == 1);
  REQUIRE(read(notification[0], &byte, 1) == 1 && byte == 'R');
  const char exit_command = 'X';
  REQUIRE(write(control[1], &exit_command, 1) == 1);
  close(control[1]);
  REQUIRE(poll(&event, 1, 1000) == 1);
  REQUIRE(read(notification[0], &byte, 1) == 1 && byte == 'T');
  close(notification[0]);
  REQUIRE(waitpid(middle, nullptr, 0) == middle);
  int worker_status = 1;
  REQUIRE(waitpid(-1, &worker_status, 0) > 0);
  REQUIRE(WIFEXITED(worker_status) && WEXITSTATUS(worker_status) == 0);
  REQUIRE(prctl(PR_SET_CHILD_SUBREAPER, 0) == 0);
}

void cold_start_can_finish_after_old_two_second_cutoff() {
  int descriptors[2];
  REQUIRE(pipe(descriptors)==0);
  REQUIRE(fcntl(descriptors[1],F_SETFL,O_NONBLOCK)==0);
  std::atomic<bool> running{true};
  std::thread reader([&] {
    std::this_thread::sleep_for(std::chrono::milliseconds(2400));
    std::vector<uint8_t> bytes(8192);
    while(read(descriptors[0],bytes.data(),bytes.size())>0) {}
  });
  aletheia::video::PipelineTiming timing;
  timing.started(0);
  // An early successful pipe write does not prove CUDA/RTSP initialization
  // finished; the remaining startup window must also cover the next frame.
  timing.written(100);
  std::vector<uint8_t> frame(640*480*3);
  int error=0;
  const bool success=aletheia::video::write_pipe(descriptors[1],frame.data(),frame.size(),running,error,
                                               timing.write_timeout_ms(100));
  close(descriptors[1]);
  reader.join();
  close(descriptors[0]);
  REQUIRE(success);
  REQUIRE(timing.write_timeout_ms(10000)==250);
  REQUIRE(timing.write_timeout_ms(9750)==250);
  REQUIRE(timing.write_timeout_ms(9900)==250);
  REQUIRE(timing.failed(10000)==1000);
  REQUIRE(timing.failed(12000)==2000);
  REQUIRE(timing.failed(15000)==4000);
  REQUIRE(timing.failed(20000)==8000);
  REQUIRE(timing.failed(30000)==16000);
  REQUIRE(timing.failed(50000)==30000);
  timing.started(60000);
  timing.written(60001);
  REQUIRE(timing.failed(60002)==30000); // one accepted frame must not reset backoff
  timing.started(100000);
  timing.written(100001);
  timing.written(160001);
  REQUIRE(timing.failed(160002)==30000); // a minute without input is not healthy playback
  timing.started(200000);
  for(int i=0;i<=60;++i) timing.written(200001+i*1000);
  REQUIRE(timing.failed(260002)==1000);
}

void long_startup_wait_remains_cancellable() {
  int descriptors[2];
  REQUIRE(pipe(descriptors)==0);
  REQUIRE(fcntl(descriptors[1],F_SETFL,O_NONBLOCK)==0);
  std::vector<uint8_t> frame(640*480*3);
  std::atomic<bool> running{true};
  std::thread cancel([&] {std::this_thread::sleep_for(std::chrono::milliseconds(50));running=false;});
  aletheia::video::PipelineTiming timing;
  timing.started(0);
  int error=0;
  const auto start=std::chrono::steady_clock::now();
  const bool written=aletheia::video::write_pipe(descriptors[1],frame.data(),frame.size(),running,error,timing.write_timeout_ms(0));
  cancel.join();
  close(descriptors[0]);close(descriptors[1]);
  REQUIRE(!written && error==ECANCELED);
  REQUIRE(std::chrono::steady_clock::now()-start<std::chrono::milliseconds(250));
}

int main() {
  try {
    int descriptors[2];
    REQUIRE(pipe(descriptors) == 0);
    REQUIRE(fcntl(descriptors[1], F_SETFL, O_NONBLOCK) == 0);
    std::atomic<bool> running{true};
    int error = 0;
    const std::vector<uint8_t> small{1, 2, 3, 4};
    REQUIRE(aletheia::video::write_pipe(descriptors[1], small.data(), small.size(), running, error, 50));
    uint8_t readback[4];
    REQUIRE(read(descriptors[0], readback, 4) == 4);
    REQUIRE(readback[0] == 1 && readback[3] == 4);
    std::vector<uint8_t> large(1024 * 1024);
    auto start = std::chrono::steady_clock::now();
    REQUIRE(!aletheia::video::write_pipe(descriptors[1], large.data(), large.size(), running, error, 50));
    auto elapsed = std::chrono::steady_clock::now() - start;
    REQUIRE(error == ETIMEDOUT);
    REQUIRE(elapsed < std::chrono::milliseconds(250));
    // A consumer taking 300ms to initialize exceeds the steady deadline but
    // completes inside the bounded first-frame allowance.
    std::vector<uint8_t> buffered(8192);
    REQUIRE(fcntl(descriptors[0], F_SETFL, O_NONBLOCK) == 0);
    while (read(descriptors[0], buffered.data(), buffered.size()) > 0) {
    }
    // Fill to EAGAIN so this check also works on systems with a large pipe.
    while (write(descriptors[1], buffered.data(), buffered.size()) > 0) {
    }
    std::atomic<bool> consuming{true};
    std::thread consumer([&] {
      std::this_thread::sleep_for(std::chrono::milliseconds(300));
      while (consuming) {
        if (read(descriptors[0], buffered.data(), buffered.size()) < 0 && errno == EAGAIN) std::this_thread::yield();
      }
    });
    std::vector<uint8_t> initial(16384);
    start = std::chrono::steady_clock::now();
    const bool initialized = aletheia::video::write_pipe(descriptors[1], initial.data(), initial.size(), running, error, 2000);
    consuming = false;
    consumer.join();
    REQUIRE(initialized);
    REQUIRE(std::chrono::steady_clock::now() - start >= std::chrono::milliseconds(300));
    running = false;
    start = std::chrono::steady_clock::now();
    REQUIRE(!aletheia::video::write_pipe(descriptors[1], large.data(), large.size(), running, error, 50));
    REQUIRE(error == ECANCELED);
    REQUIRE(std::chrono::steady_clock::now() - start < std::chrono::milliseconds(20));
    close(descriptors[0]);
    close(descriptors[1]);
    // Synthetic child only; no SDK, ROS, media executable, or device access.
    int ready[2];
    REQUIRE(pipe(ready) == 0);
    pid_t child = fork();
    REQUIRE(child >= 0);
    if (child == 0) {
      close(ready[0]);
      signal(SIGTERM, SIG_IGN);
      const char byte = 1;
      if (write(ready[1], &byte, 1) != 1) _exit(127);
      for (;;) pause();
    }
    close(ready[1]);
    char byte;
    REQUIRE(read(ready[0], &byte, 1) == 1);
    close(ready[0]);
    start = std::chrono::steady_clock::now();
    REQUIRE(aletheia::video::stop_child(child, 50));
    REQUIRE(std::chrono::steady_clock::now() - start < std::chrono::milliseconds(250));
    REQUIRE(waitpid(child, nullptr, WNOHANG) == -1 && errno == ECHILD);
    REQUIRE(aletheia::video::stop_child(child, 50));
    parent_death_reaps_native_child();
    cold_start_can_finish_after_old_two_second_cutoff();
    long_startup_wait_remains_cancellable();
    std::cout << "video pipe deadline/cancellation tests passed\n";
  } catch (const std::exception &error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
